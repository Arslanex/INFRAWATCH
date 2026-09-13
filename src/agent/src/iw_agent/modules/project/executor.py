from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from iw_agent.core.action_service import get_action_service
from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.modules.docker.compose import DEFAULT_COMPOSE_TIMEOUT
from iw_agent.modules.docker.executor import count_running_compose_containers
from iw_agent.modules.network.port_check import check_ports
from iw_agent.modules.project.detector import detect_project_profile
from iw_agent.modules.project.manifest import load_manifest, repo_dir, save_manifest
from iw_agent.modules.project.nginx_wiring import (
    build_server_names,
    ensure_https,
    ensure_proxy_site,
    ensure_static_site,
    nginx_params_from_request,
)
from iw_agent.modules.project.schemas import ProjectKind, ProjectManifest, ProjectProfile

MODULE = "project"

PROJECT_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="deploy_project",
        label="Deploy project",
        kind=ActionKind.WRITE,
        description="Deploy compose/static/proxy projects with optional nginx and HTTPS",
    ),
    ActionSpec(
        id="stop_project",
        label="Stop project",
        kind=ActionKind.WRITE,
        description="Run docker compose down for a registered compose project",
    ),
)

PROJECT_ACTIONS_BY_ID = {action.id: action for action in PROJECT_ACTIONS}


class ProjectExecutor:
    module = MODULE

    def actions(self) -> tuple[ActionSpec, ...]:
        return PROJECT_ACTIONS

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        if request.action_id not in PROJECT_ACTIONS_BY_ID:
            return _fail(request, f"unknown project action: {request.action_id}", options)

        handler = _HANDLERS.get(request.action_id)
        if handler is None:
            return _fail(request, f"handler missing for {request.action_id}", options)
        return await handler(request, options)


def _fail(request: ActionRequest, message: str, options: ExecutorOptions) -> ActionResult:
    return ActionResult(
        ok=False,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


def _load_project(request: ActionRequest) -> tuple[Path, ProjectManifest] | None:
    name = str(request.target_id or request.params.get("name") or "")
    workspace = request.params.get("workspace")
    if not name:
        return None
    from iw_agent.modules.project.collector import resolve_workspace_dir, validate_project_name

    validate_project_name(name)
    project_dir = resolve_workspace_dir(workspace) / name.lower()
    manifest = load_manifest(project_dir)
    if manifest is None:
        return None
    return project_dir, manifest


def _deploy_options(request: ActionRequest) -> dict:
    return {
        "domain": request.params.get("domain"),
        "https": bool(request.params.get("https", False)),
        "email": request.params.get("email"),
        "include_www": bool(request.params.get("include_www", True)),
        "staging": bool(request.params.get("staging", False)),
        "backend_port": request.params.get("backend_port"),
        "force": bool(request.params.get("force", False)),
        "build": bool(request.params.get("build", True)),
        "compose_timeout": float(request.params.get("compose_timeout", DEFAULT_COMPOSE_TIMEOUT)),
        "nginx_params": nginx_params_from_request(request.params),
    }


async def _run_compose_up(
    *,
    repo: Path,
    profile: ProjectProfile,
    compose_project: str,
    build: bool,
    compose_timeout: float,
    options: ExecutorOptions,
) -> ActionResult:
    service = get_action_service()
    return await service.run(
        ActionRequest(
            module="docker",
            action_id="compose_up",
            target_id=str(repo),
            params={
                "project_dir": str(repo),
                "compose_file": profile.compose_file,
                "project_name": compose_project,
                "build": build,
                "compose_timeout": compose_timeout,
            },
        ),
        options=ExecutorOptions(
            dry_run=options.dry_run,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )


async def _wire_nginx_for_deploy(
    *,
    domain: str,
    profile: ProjectProfile,
    repo: Path,
    deploy_opts: dict,
    options: ExecutorOptions,
    steps: list[str],
) -> tuple[bool, str | None, bool]:
    """Returns (ok, nginx_config_path, https_enabled)."""
    server_names = build_server_names(domain, include_www=deploy_opts["include_www"])
    nginx_params = deploy_opts["nginx_params"]
    https_enabled = False

    if profile.kind is ProjectKind.STATIC:
        static_root = profile.static_root or "."
        document_root = str((repo / static_root).resolve())
        nginx_result, config_path = await ensure_static_site(
            domain=domain,
            document_root=document_root,
            server_names=server_names,
            nginx_params=nginx_params,
            options=options,
        )
    else:
        backend_port = deploy_opts["backend_port"] or profile.suggested_backend_port
        if backend_port is None:
            steps.append("nginx skipped: backend port unknown (pass --backend-port)")
            return False, None, False
        nginx_result, config_path = await ensure_proxy_site(
            domain=domain,
            backend_port=int(backend_port),
            server_names=server_names,
            nginx_params=nginx_params,
            options=options,
        )

    steps.append(nginx_result.message)
    if not nginx_result.ok:
        return False, config_path, False

    if deploy_opts["https"]:
        email = deploy_opts["email"]
        if not email:
            steps.append("HTTPS skipped: --email is required with --https")
            return False, config_path, False
        https_result = await ensure_https(
            domain=domain,
            email=str(email),
            server_names=server_names,
            nginx_params=nginx_params,
            options=options,
            staging=deploy_opts["staging"],
            force=deploy_opts["force"],
        )
        steps.append(https_result.message)
        if not https_result.ok:
            return False, config_path, False
        https_enabled = True

    return True, config_path, https_enabled


async def _deploy_project(
    request: ActionRequest,
    options: ExecutorOptions,
) -> ActionResult:
    loaded = _load_project(request)
    if loaded is None:
        return _fail(request, "registered project name is required", options)

    project_dir, manifest = loaded
    repo = repo_dir(project_dir)
    if not repo.exists():
        return _fail(request, f"repo path missing: {repo}", options)

    profile = detect_project_profile(repo)
    deploy_opts = _deploy_options(request)
    domain = deploy_opts["domain"]
    compose_project = str(request.params.get("compose_project") or manifest.name)
    steps: list[str] = []
    compose_stdout = ""
    compose_stderr = ""

    if profile.kind is ProjectKind.DOCKERFILE:
        return _fail(request, "dockerfile-only projects are not deployable yet", options)
    if profile.kind is ProjectKind.UNKNOWN:
        return _fail(request, "project type could not be detected", options)

    if profile.kind in {ProjectKind.STATIC, ProjectKind.PROXY} and not domain:
        return _fail(request, f"{profile.kind.value} deploy requires --domain", options)

    if profile.kind is ProjectKind.PROXY and not deploy_opts["backend_port"] and profile.suggested_backend_port is None:
        return _fail(request, "proxy deploy requires --backend-port", options)

    if profile.kind is ProjectKind.DOCKER_COMPOSE:
        if not profile.compose_file:
            return _fail(request, "compose file not found in project profile", options)

        ports_to_check = sorted(set(profile.host_ports + profile.detected_ports))
        if profile.suggested_backend_port is not None:
            ports_to_check.append(profile.suggested_backend_port)
        port_checks = await check_ports(ports_to_check)
        blocking = [
            check
            for check in port_checks
            if not check.available and check.port in profile.host_ports
        ]
        if blocking and not deploy_opts["force"]:
            ports = ", ".join(str(check.port) for check in blocking)
            return _fail(
                request,
                f"host ports already in use: {ports} (retry with force=true to continue)",
                options,
            )
        if blocking:
            steps.append(
                f"warning: deploying despite busy host ports: {', '.join(map(str, profile.host_ports))}",
            )
        else:
            steps.append("port check passed")

        compose_result = await _run_compose_up(
            repo=repo,
            profile=profile,
            compose_project=compose_project,
            build=deploy_opts["build"],
            compose_timeout=deploy_opts["compose_timeout"],
            options=options,
        )
        compose_stdout = compose_result.stdout
        compose_stderr = compose_result.stderr
        steps.append(compose_result.message)
        if not compose_result.ok:
            _save_deploy_state(
                project_dir,
                manifest,
                compose_project,
                ok=False,
                message="\n".join(steps),
                running=0,
                total=0,
                profile=profile,
            )
            return ActionResult(
                ok=False,
                module=MODULE,
                action_id=request.action_id,
                message="\n".join(steps),
                stdout=compose_result.stdout,
                stderr=compose_result.stderr,
                dry_run=options.dry_run,
            )

        if options.dry_run and not domain:
            return ActionResult(
                ok=True,
                module=MODULE,
                action_id=request.action_id,
                message="\n".join(steps),
                dry_run=True,
            )

        running, total = 0, 0
        if not options.dry_run:
            running, total = await count_running_compose_containers(compose_project)
            steps.append(f"health check: {running}/{total} container(s) running")
            if running == 0 and total > 0:
                message = "\n".join(steps)
                _save_deploy_state(
                    project_dir,
                    manifest,
                    compose_project,
                    ok=False,
                    message=message,
                    running=running,
                    total=total,
                    profile=profile,
                )
                return ActionResult(
                    ok=False,
                    module=MODULE,
                    action_id=request.action_id,
                    message=message,
                    stdout=compose_result.stdout,
                    stderr=compose_result.stderr,
                )
    else:
        running, total = 0, 0
        steps.append(f"skipping compose ({profile.kind.value} project)")

    nginx_config_path: str | None = None
    https_enabled: bool | None = None
    ok = True

    if domain:
        nginx_ok, nginx_config_path, https_enabled = await _wire_nginx_for_deploy(
            domain=str(domain),
            profile=profile,
            repo=repo,
            deploy_opts=deploy_opts,
            options=options,
            steps=steps,
        )
        ok = nginx_ok
        if profile.kind is ProjectKind.DOCKER_COMPOSE and ok and not options.dry_run:
            ok = running > 0 or total == 0
    elif profile.kind is ProjectKind.DOCKER_COMPOSE and not options.dry_run:
        ok = running > 0 or total == 0

    message = "\n".join(steps)
    if not options.dry_run:
        _save_deploy_state(
            project_dir,
            manifest,
            compose_project,
            ok=ok,
            message=message,
            running=running,
            total=total,
            profile=profile,
            domain=str(domain) if domain else None,
            nginx_config_path=nginx_config_path,
            https_enabled=https_enabled,
        )

    return ActionResult(
        ok=ok,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        stdout=compose_stdout,
        stderr=compose_stderr,
        dry_run=options.dry_run,
    )


async def _stop_project(
    request: ActionRequest,
    options: ExecutorOptions,
) -> ActionResult:
    loaded = _load_project(request)
    if loaded is None:
        return _fail(request, "registered project name is required", options)

    project_dir, manifest = loaded
    repo = repo_dir(project_dir)
    profile = manifest.profile
    if profile.kind is not ProjectKind.DOCKER_COMPOSE or not profile.compose_file:
        return _fail(request, "stop supports deployed docker-compose projects only", options)

    compose_project = str(
        request.params.get("compose_project")
        or manifest.deploy.compose_project
        or manifest.name,
    )
    compose_timeout = float(request.params.get("compose_timeout", DEFAULT_COMPOSE_TIMEOUT))

    service = get_action_service()
    result = await service.run(
        ActionRequest(
            module="docker",
            action_id="compose_down",
            target_id=str(repo),
            params={
                "project_dir": str(repo),
                "compose_file": profile.compose_file,
                "project_name": compose_project,
                "compose_timeout": compose_timeout,
            },
        ),
        options=ExecutorOptions(
            dry_run=options.dry_run,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )

    if result.ok and not options.dry_run:
        manifest.deploy.last_deploy_ok = False
        manifest.deploy.containers_running = 0
        manifest.deploy.last_message = "stopped via compose down"
        manifest.deploy.last_deploy_at = datetime.now(timezone.utc)
        save_manifest(project_dir, manifest)

    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message=result.message,
        stdout=result.stdout,
        stderr=result.stderr,
        dry_run=options.dry_run,
    )


def _save_deploy_state(
    project_dir: Path,
    manifest,
    compose_project: str,
    *,
    ok: bool,
    message: str,
    running: int,
    total: int,
    profile=None,
    domain: str | None = None,
    nginx_config_path: str | None = None,
    https_enabled: bool | None = None,
) -> None:
    if profile is not None:
        manifest.profile = profile
    manifest.deploy.compose_project = compose_project
    manifest.deploy.last_deploy_at = datetime.now(timezone.utc)
    manifest.deploy.last_deploy_ok = ok
    manifest.deploy.last_message = message
    manifest.deploy.containers_running = running
    manifest.deploy.containers_total = total
    if domain is not None:
        manifest.deploy.domain = domain
    if nginx_config_path is not None:
        manifest.deploy.nginx_config_path = nginx_config_path
    if https_enabled is not None:
        manifest.deploy.https_enabled = https_enabled
    save_manifest(project_dir, manifest)


_HANDLERS = {
    "deploy_project": _deploy_project,
    "stop_project": _stop_project,
}
