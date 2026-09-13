from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import Navigator, Page, PageContext, PageResult
from iw_agent.cli.interactive.selector import prompt_choice
from iw_agent.cli.output import (
    emit_models,
    format_field,
    format_optional,
    format_state,
    print_empty,
    print_group_heading,
    print_insight,
    print_menu_item,
    print_page_divider,
    print_page_summary,
    print_report,
    print_status_box,
    prepare_command_view,
    status_badge,
)
from iw_agent.cli.parser import add_interactive_flags, add_limit_flag, add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError
from iw_agent.modules.docker.collector import (
    DEFAULT_CONTAINER_LIMIT,
    DEFAULT_DOCKER_SOCKET_PATH,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    collect_containers,
)
from iw_agent.modules.docker.schemas import Container, PublishedPort


async def run_containers(args: argparse.Namespace) -> None:
    if getattr(args, "interactive", False):
        await run_containers_interactive(args)
        return

    containers = await collect_containers(
        socket_path=args.socket_path,
        timeout=args.timeout,
        limit=args.limit,
    )
    emit_models(containers, json_output=args.json, plain=args.plain, render=_render_containers)


def _containers_summary(containers: list[Container]) -> str:
    running = sum(1 for container in containers if container.state.lower() == "running")
    projects = {
        container.compose_project_name
        for container in containers
        if container.compose_project_name
    }
    project_text = f"{len(projects)} compose project(s)" if projects else "no compose projects"
    return f"Found {len(containers)} container(s), {running} running, {project_text}."


def _project_label(container: Container) -> str:
    if container.compose_project_name:
        return container.compose_project_name
    return "standalone"


def _format_ports(ports: list[PublishedPort]) -> str:
    if not ports:
        return "—"
    return ", ".join(str(port) for port in ports)


def _short_ports(ports: list[PublishedPort]) -> str:
    if not ports:
        return ""
    host_ports = [
        str(port.host_port)
        for port in ports
        if port.host_port is not None
    ]
    if not host_ports:
        return ""
    return ":" + ",".join(host_ports)


def _container_badge(state: str) -> tuple[str, str]:
    lowered = state.lower()
    if lowered == "running":
        return status_badge("RUNNING", "ok"), "ok"
    if lowered in {"exited", "stopped", "dead"}:
        return status_badge("STOPPED", "off"), "off"
    return status_badge(state.upper(), "warn"), "warn"


def _render_container_card(container: Container) -> None:
    badge, tone = _container_badge(container.state)
    lines = [
        format_field("Project", format_optional(container.compose_project_name, fallback="—")),
        format_field("Image", container.image_name),
    ]

    if container.compose_service_name:
        lines.append(format_field("Service", container.compose_service_name))

    lines.extend(
        [
            format_field("Status", format_state(container.state)),
            format_field("Ports", _format_ports(container.published_ports)),
            format_field("ID", container.container_id[:12]),
        ]
    )

    print_status_box(
        badge=badge,
        title=container.container_name,
        lines=lines,
        tone=tone,
        strike_title=container.state.lower() in {"exited", "stopped", "dead"},
    )


def _group_containers(containers: list[Container]) -> list[tuple[str, list[Container]]]:
    grouped: dict[str, list[Container]] = defaultdict(list)
    for container in containers:
        grouped[_project_label(container)].append(container)

    def sort_key(project_name: str) -> tuple[int, str]:
        if project_name == "standalone":
            return (1, project_name)
        return (0, project_name.lower())

    return sorted(grouped.items(), key=lambda item: sort_key(item[0]))


def _ordered_containers(containers: list[Container]) -> list[Container]:
    ordered: list[Container] = []
    for _, project_containers in _group_containers(containers):
        ordered.extend(
            sorted(project_containers, key=lambda row: row.container_name.lower())
        )
    return ordered


def _render_containers(containers: list[Container]) -> None:
    print_report(
        "Docker containers",
        "Isolated application boxes managed by Docker.",
    )
    if not containers:
        print_empty(
            "no containers",
            "Docker is not running, not installed, or no containers exist.",
            "install Docker and run: sudo apt install docker.io && sudo systemctl start docker",
        )
        return

    print_insight(_containers_summary(containers))

    for project_name, project_containers in _group_containers(containers):
        if project_name == "standalone":
            print_group_heading("Standalone containers", "not tied to a compose project")
        else:
            print_group_heading(f"Project: {project_name}", "started by docker compose")

        for container in sorted(project_containers, key=lambda row: row.container_name.lower()):
            _render_container_card(container)


def _configure(parser: argparse.ArgumentParser) -> None:
    add_interactive_flags(parser)
    add_limit_flag(parser, default=DEFAULT_CONTAINER_LIMIT, help_text="max containers")
    add_timeout_flag(parser, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument(
        "--socket",
        dest="socket_path",
        default=DEFAULT_DOCKER_SOCKET_PATH,
        help=f"docker socket path (default: {DEFAULT_DOCKER_SOCKET_PATH})",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=100,
        help="log lines to show in interactive mode (default: 100)",
    )


@dataclass(frozen=True)
class _HubEntry:
    label: str
    hint: str = ""
    action_id: str = ""
    kind: str = "action"


def _container_params(context: PageContext, container: Container) -> dict:
    return {
        "container_id": container.container_id,
        "socket_path": context.args.socket_path,
        "timeout": context.args.timeout,
        "limit": context.args.limit,
        "tail": context.args.tail,
    }


def _container_list_hint(container: Container) -> str:
    state = container.state.lower()
    parts = [state]
    project = container.compose_project_name
    if project:
        parts.append(f"compose:{project}")
    ports = _short_ports(container.published_ports)
    if ports:
        parts.append(ports)
    return " · ".join(parts)


def _container_is_running(container: Container) -> bool:
    return container.state.lower() == "running"


def _container_hub_menu(container: Container) -> list[_HubEntry]:
    if _container_is_running(container):
        return [
            _HubEntry("Restart", "stop then start", "restart_container"),
            _HubEntry("Stop", "graceful shutdown", "stop_container"),
            _HubEntry("Logs", "last stdout/stderr lines", "view_logs"),
            _HubEntry("More", "image, ports, compose"),
        ]
    return [
        _HubEntry("Start", "bring container up", "start_container"),
        _HubEntry("Logs", "last stdout/stderr lines", "view_logs"),
        _HubEntry("More", "image, ports, compose"),
    ]


async def _refresh_containers(context: PageContext) -> None:
    args = context.args
    containers = await collect_containers(
        socket_path=args.socket_path,
        timeout=args.timeout,
        limit=args.limit,
    )
    context.data["containers"] = _ordered_containers(containers)


async def _run_container_action(
    context: PageContext,
    container: Container,
    action_id: str,
) -> ActionResult | None:
    request = ActionRequest(
        module="docker",
        action_id=action_id,
        target_id=container.container_id,
        params=_container_params(context, container),
    )
    try:
        return await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=container.container_name,
        )
    except ActionCancelledError:
        print("\nCancelled.")
        return None
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        return None


async def run_containers_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    containers = _ordered_containers(
        await collect_containers(
            socket_path=args.socket_path,
            timeout=args.timeout,
            limit=args.limit,
        )
    )
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"containers": containers, "options": options},
    )
    await Navigator(context).run(_InteractiveContainerListPage())


class _InteractiveContainerListPage(Page):
    @property
    def title(self) -> str:
        return "Containers"

    @property
    def subtitle(self) -> str:
        return "docker"

    def render(self, context: PageContext) -> None:
        containers: list[Container] = context.data["containers"]
        print_page_divider()
        if not containers:
            print_page_summary(
                "No containers found. Docker may be stopped or the socket is unreachable.",
            )
            return

        index = 1
        for project_name, project_containers in _group_containers(containers):
            if project_name == "standalone":
                heading = "Standalone"
            else:
                heading = f"compose: {project_name}"
            print_page_summary(heading)
            for container in sorted(
                project_containers,
                key=lambda row: row.container_name.lower(),
            ):
                print_menu_item(index, container.container_name, _container_list_hint(container))
                index += 1

    async def handle(self, context: PageContext) -> PageResult | Page:
        containers: list[Container] = context.data["containers"]
        if not containers:
            return PageResult.EXIT

        choice = prompt_choice(max_value=len(containers), allow_back=False, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        return _InteractiveContainerDetailPage(containers[choice - 1])


class _InteractiveContainerDetailPage(Page):
    def __init__(self, container: Container) -> None:
        self._container = container
        self._menu = _container_hub_menu(container)

    @property
    def title(self) -> str:
        return self._container.container_name

    @property
    def subtitle(self) -> str:
        return "docker"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        print_page_summary(_container_list_hint(self._container))
        if self._container.image_name:
            print(f"   image: {self._container.image_name}")
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
        if entry.kind == "more" or not entry.action_id:
            return _ContainerMorePage(self._container)

        result = await _run_container_action(context, self._container, entry.action_id)
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        if entry.action_id == "view_logs":
            if result.stdout:
                print(result.stdout)
            else:
                print_action_result(result)
        else:
            print_action_result(result)
        input("\nPress Enter to continue...")

        if result.ok and entry.action_id in {
            "start_container",
            "stop_container",
            "restart_container",
        }:
            await _refresh_containers(context)
            refreshed = next(
                (
                    container
                    for container in context.data["containers"]
                    if container.container_id == self._container.container_id
                ),
                self._container,
            )
            self._container = refreshed
            self._menu = _container_hub_menu(refreshed)
        return PageResult.STAY


class _ContainerMorePage(Page):
    def __init__(self, container: Container) -> None:
        self._container = container

    @property
    def title(self) -> str:
        return self._container.container_name

    @property
    def subtitle(self) -> str:
        return "docker · more"

    def render(self, context: PageContext) -> None:
        container = self._container
        print_page_divider()
        print_page_summary(format_state(container.state))
        print(f"\n   Image: {container.image_name}")
        print(f"   ID: {container.container_id[:12]}")
        if container.compose_project_name:
            print(f"   Compose project: {container.compose_project_name}")
        if container.compose_service_name:
            print(f"   Compose service: {container.compose_service_name}")
        print(f"   Ports: {_format_ports(container.published_ports)}")
        if container.status_message:
            print(f"   Status: {container.status_message}")
        print_page_divider()
        print_menu_item(1, "View details")

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=1, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        result = await _run_container_action(context, self._container, "view_details")
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print(result.message)
        input("\nPress Enter to continue...")
        return PageResult.STAY


COMMAND_SPECS = [
    CliCommandSpec("containers", "docker containers", run_containers, _configure),
]
