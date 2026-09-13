from __future__ import annotations

import argparse
from collections import defaultdict

from iw_agent.cli.output import (
    emit_models,
    format_field,
    format_optional,
    format_state,
    print_empty,
    print_group_heading,
    print_insight,
    print_report,
    print_status_box,
    status_badge,
)
from iw_agent.cli.parser import add_limit_flag, add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.docker.collector import (
    DEFAULT_CONTAINER_LIMIT,
    DEFAULT_DOCKER_SOCKET_PATH,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    collect_containers,
)
from iw_agent.modules.docker.schemas import Container, PublishedPort


async def run_containers(args: argparse.Namespace) -> None:
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
    add_limit_flag(parser, default=DEFAULT_CONTAINER_LIMIT, help_text="max containers")
    add_timeout_flag(parser, default=DEFAULT_REQUEST_TIMEOUT_SECONDS)
    parser.add_argument(
        "--socket",
        dest="socket_path",
        default=DEFAULT_DOCKER_SOCKET_PATH,
        help=f"docker socket path (default: {DEFAULT_DOCKER_SOCKET_PATH})",
    )


COMMAND_SPECS = [
    CliCommandSpec("containers", "docker containers", run_containers, _configure),
]
