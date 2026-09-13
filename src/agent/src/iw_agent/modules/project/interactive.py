from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import Navigator, Page, PageContext, PageResult
from iw_agent.cli.interactive.selector import prompt_choice, prompt_yes_no
from iw_agent.cli.output import (
    format_field,
    prepare_command_view,
    print_menu_item,
    print_page_divider,
    print_page_summary,
)
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError, ProjectError
from iw_agent.modules.project.collector import (
    add_project,
    detect_project,
    list_projects,
    resolve_workspace_dir,
)
from iw_agent.modules.project.manifest import load_manifest
from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary
from iw_agent.modules.nginx.schemas import VirtualHost

_DOMAIN_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _HubEntry:
    label: str
    hint: str
    action: str


def _valid_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.match(domain))


def _project_hint(project: ProjectSummary) -> str:
    parts = [project.kind.value]
    if project.deploy_ok:
        parts.append(f"running ({project.containers_running})")
    return " · ".join(parts)


def _project_hub_menu(project: ProjectSummary) -> list[_HubEntry]:
    menu = [
        _HubEntry("Detect", "refresh stack type and port checks", "detect"),
        _HubEntry("Deploy", "compose up (nginx edits happen in the editor)", "deploy"),
        _HubEntry("Edit nginx", "open site config in the structural editor", "nginx"),
    ]
    if project.kind is ProjectKind.DOCKER_COMPOSE:
        menu.append(_HubEntry("Stop", "docker compose down", "stop"))
    menu.append(_HubEntry("More", "repo path and manifest details", "more"))
    return menu


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
    try:
        return await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=name,
        )
    except ActionCancelledError:
        print("\nCancelled.")
        return None
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        return None


async def run_project_interactive(args) -> None:
    prepare_command_view(plain=getattr(args, "plain", False))
    projects = await list_projects(getattr(args, "workspace", None))
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"projects": projects, "options": options},
    )
    await Navigator(context).run(_InteractiveProjectListPage())


class _InteractiveProjectListPage(Page):
    @property
    def title(self) -> str:
        return "Projects"

    @property
    def subtitle(self) -> str:
        return "project"

    async def on_enter(self, context: PageContext) -> None:
        await _refresh_projects(context)

    def render(self, context: PageContext) -> None:
        projects: list[ProjectSummary] = context.data["projects"]
        workspace = resolve_workspace_dir(getattr(context.args, "workspace", None))
        print_page_divider()
        print_page_summary(f"Workspace: {workspace}")
        if not projects:
            print_page_summary("No registered projects yet.")
            print_menu_item(1, "Add project", "git clone or local path")
            return

        for index, project in enumerate(projects, start=1):
            print_menu_item(index, project.name, _project_hint(project))
        print_menu_item(len(projects) + 1, "Add project", "git clone or local path")

    async def handle(self, context: PageContext) -> PageResult | Page:
        projects: list[ProjectSummary] = context.data["projects"]
        max_value = max(len(projects), 0) + 1
        choice = prompt_choice(max_value=max_value, allow_back=False, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == max_value:
            return _InteractiveAddPage()
        return _InteractiveProjectDetailPage(projects[choice - 1])


class _InteractiveProjectDetailPage(Page):
    def __init__(self, project: ProjectSummary) -> None:
        self._project = project
        self._menu = _project_hub_menu(project)

    @property
    def title(self) -> str:
        return self._project.name

    @property
    def subtitle(self) -> str:
        return "project"

    def render(self, context: PageContext) -> None:
        project = self._project
        print_page_divider()
        print_page_summary(_project_hint(project))
        manifest = load_manifest(
            resolve_workspace_dir(getattr(context.args, "workspace", None)) / project.name,
        )
        if manifest and manifest.deploy.domain:
            print(f"\n   Domain: {manifest.deploy.domain}")
            if manifest.deploy.https_enabled:
                print("   HTTPS: enabled")
        print_page_divider()
        for index, entry in enumerate(self._menu, start=1):
            print_menu_item(index, entry.label, entry.hint)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._menu), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        entry = self._menu[choice - 1]
        if entry.action == "detect":
            return await self._run_detect(context)
        if entry.action == "deploy":
            return _InteractiveDeployPage(self._project)
        if entry.action == "nginx":
            await _open_project_nginx_editor(context, self._project)
            return PageResult.STAY
        if entry.action == "stop":
            return await self._run_stop(context)
        return _InteractiveProjectMorePage(self._project)

    async def _run_detect(self, context: PageContext) -> PageResult:
        try:
            result = await detect_project(
                self._project.name,
                workspace=getattr(context.args, "workspace", None),
                save=True,
            )
        except ProjectError as exc:
            print(f"\n{exc.message}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print(f"\nDetected {result.profile.kind.value}")
        if result.hints:
            print(f"Hints: {'; '.join(result.hints)}")
        input("\nPress Enter to continue...")
        await _refresh_projects(context)
        refreshed = next(
            (row for row in context.data["projects"] if row.name == self._project.name),
            self._project,
        )
        self._project = refreshed
        self._menu = _project_hub_menu(refreshed)
        return PageResult.STAY

    async def _run_stop(self, context: PageContext) -> PageResult:
        result = await _run_project_action(context, self._project.name, "stop_project")
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY
        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
        if result.ok:
            await _refresh_projects(context)
            refreshed = next(
                (row for row in context.data["projects"] if row.name == self._project.name),
                self._project,
            )
            self._project = refreshed
            self._menu = _project_hub_menu(refreshed)
        return PageResult.STAY


class _InteractiveProjectMorePage(Page):
    def __init__(self, project: ProjectSummary) -> None:
        self._project = project

    @property
    def title(self) -> str:
        return self._project.name

    @property
    def subtitle(self) -> str:
        return "project · details"

    def render(self, context: PageContext) -> None:
        project = self._project
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

    async def handle(self, context: PageContext) -> PageResult | Page:
        input("\nPress Enter to continue...")
        return PageResult.BACK


class _InteractiveAddPage(Page):
    @property
    def title(self) -> str:
        return "Add project"

    @property
    def subtitle(self) -> str:
        return "project"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        print_page_summary("Git URL or local directory path.")

    async def handle(self, context: PageContext) -> PageResult | Page:
        source = input("\nSource: ").strip()
        if not source:
            print("Source is required.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY

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
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print(f"\nAdded {manifest.name} ({manifest.profile.kind.value})")
        input("\nPress Enter to continue...")
        await _refresh_projects(context)
        project = next(
            (row for row in context.data["projects"] if row.name == manifest.name),
            None,
        )
        if project is not None:
            return _InteractiveProjectDetailPage(project)
        return PageResult.BACK


class _InteractiveDeployPage(Page):
    def __init__(self, project: ProjectSummary) -> None:
        self._project = project

    @property
    def title(self) -> str:
        return f"Deploy {self._project.name}"

    @property
    def subtitle(self) -> str:
        return "project"

    def render(self, context: PageContext) -> None:
        project = self._project
        print_page_divider()
        print_page_summary(f"{project.kind.value} · {_project_hint(project)}")

    async def handle(self, context: PageContext) -> PageResult | Page:
        project = self._project
        try:
            detect = await detect_project(
                project.name,
                workspace=getattr(context.args, "workspace", None),
                save=False,
            )
        except ProjectError as exc:
            print(f"\n{exc.message}", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY

        profile = detect.profile
        if profile.kind is ProjectKind.DOCKERFILE:
            print("\nDockerfile-only projects are not deployable yet.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.BACK

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
            input("\nPress Enter to continue...")
            return PageResult.BACK

        domain = ""
        if configure_nginx:
            domain = input("\nDomain (e.g. app.example.com): ").strip().lower()
            if not domain:
                print("Domain is required.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            if not _valid_domain(domain):
                print("Enter a valid domain name.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
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
                        input("\nPress Enter to continue...")
                        return PageResult.STAY
                elif default_port is not None:
                    params["backend_port"] = default_port
                elif profile.kind is ProjectKind.PROXY:
                    print("Backend port is required for proxy projects.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return PageResult.STAY

            if prompt_yes_no("\nSet up HTTPS (Let's Encrypt)?", default=False):
                email = input("\nLet's Encrypt email: ").strip()
                if not email:
                    print("Email is required for HTTPS.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
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
            return PageResult.STAY

        result = await _run_project_action(
            context,
            project.name,
            "deploy_project",
            extra_params=params,
        )
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
        if result.ok:
            await _refresh_projects(context)
            refreshed = next(
                (row for row in context.data["projects"] if row.name == project.name),
                project,
            )
            return _InteractiveProjectDetailPage(refreshed)
        return PageResult.STAY
