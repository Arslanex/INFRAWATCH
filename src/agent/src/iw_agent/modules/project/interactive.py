from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import pause, run_action_in_hub
from iw_agent.cli.interactive.context import PageContext
from iw_agent.cli.interactive.hub import pick_or_fallback, run_action_hub
from iw_agent.cli.interactive.selector import prompt_choice, prompt_yes_no
from iw_agent.cli.output import (
    format_field,
    prepare_command_view,
    print_menu_item,
    print_page_divider,
    print_page_summary,
)
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.core.exceptions import ProjectError
from iw_agent.modules.project.collector import (
    add_project,
    detect_project,
    list_projects,
    resolve_workspace_dir,
)
from iw_agent.modules.project.display import project_status_label, publish_wizard_intro
from iw_agent.modules.project.manifest import load_manifest
from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary
from iw_agent.modules.nginx.schemas import VirtualHost

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$",
    re.IGNORECASE,
)


def _valid_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.match(domain))


def _project_hint(project: ProjectSummary) -> str:
    return f"{project.kind.value} · {project_status_label(project)}"


def _projects_summary(projects: list[ProjectSummary], workspace: Path) -> str:
    if not projects:
        return f"Workspace: {workspace} · no registered projects yet."
    return f"Workspace: {workspace} · {len(projects)} project(s)."


def _nginx_editor_args(context: PageContext) -> argparse.Namespace:
    args = context.args
    return argparse.Namespace(
        nginx_binary=getattr(args, "nginx_binary", "nginx"),
        timeout=getattr(args, "timeout", 30.0),
        certbot_live_dir=getattr(args, "certbot_live_dir", "/etc/letsencrypt/live"),
        staging=getattr(args, "staging", False),
        dry_run=getattr(args, "dry_run", False),
        plain=getattr(args, "plain", False),
        site=None,
    )


async def _open_project_nginx_editor(context: PageContext, project: ProjectSummary) -> bool:
    from iw_agent.modules.nginx.collector import DEFAULT_SITES_AVAILABLE_DIR
    from iw_agent.modules.nginx.commands import _open_editor

    manifest = load_manifest(
        resolve_workspace_dir(getattr(context.args, "workspace", None)) / project.name,
    )
    if manifest is None:
        print("\nProject manifest not found.", file=sys.stderr)
        return False

    domain = manifest.deploy.domain
    config_path = manifest.deploy.nginx_config_path
    if not config_path and domain:
        config_path = str(Path(DEFAULT_SITES_AVAILABLE_DIR) / domain)
    if not config_path or not Path(config_path).is_file():
        print(
            "\nNo nginx config for this project yet.",
            file=sys.stderr,
        )
        print(
            "Deploy with --domain or create the site in `iw nginx -i` first.",
            file=sys.stderr,
        )
        return False

    server_names = [domain] if domain else []
    host = VirtualHost(config_path=config_path, server_names=server_names)
    await _open_editor(_nginx_editor_args(context), host)
    return True


async def _refresh_projects(context: PageContext) -> None:
    projects = await list_projects(getattr(context.args, "workspace", None))
    context.data["projects"] = projects


async def _run_project_action(
    context: PageContext,
    name: str,
    action_id: str,
    *,
    extra_params: dict | None = None,
) -> ActionResult | None:
    params = {
        "name": name,
        "workspace": getattr(context.args, "workspace", None),
        "build": True,
        "force": False,
        "compose_timeout": getattr(context.args, "timeout", 600.0),
        "include_www": True,
        "staging": getattr(context.args, "staging", False),
    }
    if extra_params:
        params.update(extra_params)

    request = ActionRequest(
        module="project",
        action_id=action_id,
        target_id=name,
        params=params,
    )
    return await run_action_in_hub(
        request,
        options=context.data["options"],
        target_label=name,
    )


async def _interactive_pick_project(
    args: argparse.Namespace,
    projects: list[ProjectSummary],
    workspace: Path,
):
    from iw_agent.modules.project.project_picker import pick_project

    return await pick_or_fallback(
        lambda: pick_project(
            projects,
            summary=_projects_summary(projects, workspace),
            dry_run=getattr(args, "dry_run", False),
        ),
        lambda: _interactive_pick_project_fallback(projects, workspace),
    )


async def _interactive_pick_project_fallback(
    projects: list[ProjectSummary],
    workspace: Path,
):
    from iw_agent.cli.output import clear_screen, print_page_header
    from iw_agent.modules.project.project_picker import ProjectListChoice

    clear_screen()
    print_page_header("Projects", "project")
    print_page_divider()
    print_page_summary(_projects_summary(projects, workspace))
    for index, project in enumerate(projects, start=1):
        print_menu_item(index, project.name, _project_hint(project))
    add_index = len(projects) + 1
    print_menu_item(add_index, "Register project", "git URL or existing local clone")
    choice = prompt_choice(max_value=add_index, allow_back=False, allow_exit=True)
    if choice is None:
        return None
    if choice == add_index:
        return ProjectListChoice(kind="add")
    return ProjectListChoice(kind="project", project=projects[choice - 1])


async def _interactive_add_project(context: PageContext) -> ProjectSummary | None:
    print_page_divider()
    print_page_summary(
        "Register a git URL or an existing local clone. "
        "InfraWatch records the repo — it does not start your app.",
    )

    source = input("\nSource: ").strip()
    if not source:
        print("Source is required.", file=sys.stderr)
        pause()
        return None

    name = input("\nProject name (optional): ").strip() or None
    try:
        manifest = await add_project(
            source,
            name=name,
            workspace=getattr(context.args, "workspace", None),
            git_timeout=getattr(context.args, "timeout", 120.0),
        )
    except ProjectError as exc:
        print(f"\n{exc.message}", file=sys.stderr)
        pause()
        return None

    print(f"\nAdded {manifest.name} ({manifest.profile.kind.value})")
    pause()
    await _refresh_projects(context)
    return next(
        (row for row in context.data["projects"] if row.name == manifest.name),
        None,
    )


async def _run_detect(context: PageContext, project: ProjectSummary) -> ProjectSummary:
    try:
        result = await detect_project(
            project.name,
            workspace=getattr(context.args, "workspace", None),
            save=True,
        )
    except ProjectError as exc:
        print(f"\n{exc.message}", file=sys.stderr)
        pause()
        return project

    print(f"\nDetected {result.profile.kind.value}")
    if result.hints:
        print(f"Hints: {'; '.join(result.hints)}")
    pause()
    await _refresh_projects(context)
    return next(
        (row for row in context.data["projects"] if row.name == project.name),
        project,
    )


async def _run_stop(context: PageContext, project: ProjectSummary) -> ProjectSummary:
    result = await _run_project_action(context, project.name, "stop_project")
    if result is None:
        pause()
        return project
    print()
    print_action_result(result)
    pause()
    if result.ok:
        await _refresh_projects(context)
        return next(
            (row for row in context.data["projects"] if row.name == project.name),
            project,
        )
    return project


async def _show_project_more(context: PageContext, project: ProjectSummary) -> None:
    manifest = load_manifest(
        resolve_workspace_dir(getattr(context.args, "workspace", None)) / project.name,
    )
    print_page_divider()
    print(format_field("Type", project.kind.value))
    print(format_field("Source", project.source_type))
    print(format_field("Repo", project.repo_path))
    if project.suggested_backend_port is not None:
        print(format_field("Backend port", str(project.suggested_backend_port)))
    if project.host_ports:
        print(format_field("Host ports", ", ".join(map(str, project.host_ports))))
    if manifest:
        print(format_field("Manifest", str(manifest.workspace_path)))
        if manifest.deploy.last_message:
            print(format_field("Last deploy", manifest.deploy.last_message[:120]))
    pause()


async def _interactive_deploy_project(
    context: PageContext,
    project: ProjectSummary,
) -> ProjectSummary:
    print_page_divider()
    print_page_summary(f"{project.kind.value} · {_project_hint(project)}")

    try:
        detect = await detect_project(
            project.name,
            workspace=getattr(context.args, "workspace", None),
            save=False,
        )
    except ProjectError as exc:
        print(f"\n{exc.message}", file=sys.stderr)
        pause()
        return project

    profile = detect.profile
    if profile.kind is ProjectKind.DOCKERFILE:
        print("\nDockerfile-only projects are not deployable yet.", file=sys.stderr)
        pause()
        return project

    print_page_divider()
    print_page_summary(publish_wizard_intro(profile.kind))

    params: dict = {
        "build": True,
        "force": False,
        "include_www": True,
        "staging": getattr(context.args, "staging", False),
    }

    needs_domain = profile.kind in {ProjectKind.STATIC, ProjectKind.PROXY}
    configure_nginx = needs_domain

    if profile.kind is ProjectKind.DOCKER_COMPOSE:
        configure_nginx = prompt_yes_no("\nConfigure nginx for a public domain?", default=False)
    elif not needs_domain:
        print("\nProject type could not be deployed.", file=sys.stderr)
        pause()
        return project

    domain = ""
    if configure_nginx:
        domain = input("\nDomain (e.g. app.example.com): ").strip().lower()
        if not domain:
            print("Domain is required.", file=sys.stderr)
            pause()
            return project
        if not _valid_domain(domain):
            print("Enter a valid domain name.", file=sys.stderr)
            pause()
            return project
        params["domain"] = domain
        params["include_www"] = prompt_yes_no(f"\nAlso serve www.{domain}?", default=True)

        if profile.kind in {ProjectKind.DOCKER_COMPOSE, ProjectKind.PROXY}:
            default_port = profile.suggested_backend_port
            port_hint = str(default_port) if default_port is not None else "8080"
            raw_port = input(f"\nBackend port [{port_hint}]: ").strip()
            if raw_port:
                try:
                    params["backend_port"] = int(raw_port)
                except ValueError:
                    print("Enter a valid port number.", file=sys.stderr)
                    pause()
                    return project
            elif default_port is not None:
                params["backend_port"] = default_port
            elif profile.kind is ProjectKind.PROXY:
                print("Backend port is required for proxy projects.", file=sys.stderr)
                pause()
                return project
            if profile.kind is ProjectKind.PROXY and params.get("backend_port") is not None:
                from iw_agent.modules.network.port_check import check_ports

                port = int(params["backend_port"])
                checks = await check_ports([port])
                if checks and checks[0].note == "no listener on this port":
                    print(f"\n  warning: nothing is listening on port {port} yet.")
                    print("  Start your app (e.g. uvicorn) or choose another port.")
                    if not prompt_yes_no("Continue anyway?", default=False):
                        return project
                elif checks and checks[0].listener:
                    print(f"\n  backend: {checks[0].listener}")

        if prompt_yes_no("\nSet up HTTPS (Let's Encrypt)?", default=False):
            email = input("\nLet's Encrypt email: ").strip()
            if not email:
                print("Email is required for HTTPS.", file=sys.stderr)
                pause()
                return project
            params["https"] = True
            params["email"] = email
            if not params["staging"]:
                params["staging"] = prompt_yes_no(
                    "Use Let's Encrypt staging (test cert)?",
                    default=False,
                )

    if profile.kind is ProjectKind.DOCKER_COMPOSE:
        params["build"] = prompt_yes_no("\nBuild images (docker compose --build)?", default=True)
        if detect.port_checks:
            busy = [check for check in detect.port_checks if not check.available]
            if busy:
                ports = ", ".join(str(check.port) for check in busy)
                print(f"\n  warning: ports may be busy: {ports}")
                params["force"] = prompt_yes_no("Deploy anyway?", default=False)

    print("\nPreview:")
    print(f"  project: {project.name}")
    print(f"  kind: {profile.kind.value}")
    if domain:
        print(f"  domain: {domain}")
    if params.get("backend_port") is not None:
        print(f"  backend_port: {params['backend_port']}")
    print(f"  https: {'yes' if params.get('https') else 'no'}")
    print(f"  dry_run: {'yes' if context.data['options'].dry_run else 'no'}")

    if not prompt_yes_no("\nRun deploy?", default=True):
        return project

    result = await _run_project_action(
        context,
        project.name,
        "deploy_project",
        extra_params=params,
    )
    if result is None:
        pause()
        return project

    print()
    print_action_result(result)
    pause()
    if result.ok:
        await _refresh_projects(context)
        return next(
            (row for row in context.data["projects"] if row.name == project.name),
            project,
        )
    return project


async def _perform_project_action(
    context: PageContext,
    project: ProjectSummary,
    action: str,
) -> ProjectSummary:
    if action == "detect":
        return await _run_detect(context, project)
    if action == "deploy":
        return await _interactive_deploy_project(context, project)
    if action == "nginx":
        await _open_project_nginx_editor(context, project)
        return project
    if action == "stop":
        return await _run_stop(context, project)
    await _show_project_more(context, project)
    return project


async def _interactive_project_hub(
    context: PageContext,
    project: ProjectSummary,
) -> bool:
    from iw_agent.modules.project.action_picker import pick_project_action

    return await run_action_hub(
        project,
        pick=lambda target: pick_project_action(
            target,
            dry_run=context.data["options"].dry_run,
        ),
        perform=lambda target, action: _perform_project_action(
            context,
            target,
            action.action_id,
        ),
    )


async def run_project_interactive(args) -> None:
    prepare_command_view(plain=getattr(args, "plain", False))
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"projects": [], "options": options},
    )
    workspace = resolve_workspace_dir(getattr(args, "workspace", None))

    while True:
        await _refresh_projects(context)
        projects = context.data["projects"]
        picked = await _interactive_pick_project(args, projects, workspace)
        if picked.quit_session:
            break
        if picked.value is None:
            continue
        if picked.value.kind == "add":
            added = await _interactive_add_project(context)
            if added is not None and await _interactive_project_hub(context, added):
                break
            continue
        if await _interactive_project_hub(context, picked.value.project):
            break
