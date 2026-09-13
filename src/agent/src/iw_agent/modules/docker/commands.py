from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    format_state,
    print_column_guide,
    print_data_table,
    print_empty,
    print_insight,
    print_report,
    print_section,
)
from iw_agent.cli.parser import add_limit_flag, add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.docker.collector import (
    DEFAULT_CONTAINER_LIMIT,
    DEFAULT_DOCKER_SOCKET_PATH,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    collect_containers,
)
from iw_agent.modules.docker.schemas import Container

CONTAINER_COLUMNS = [
    ("Name", "container name"),
    ("Status", "running, stopped, etc."),
    ("App image", "software package inside the container"),
    ("Project", "docker compose project, if any"),
    ("Published ports", "ports exposed to the host"),
]


async def run_containers(args: argparse.Namespace) -> None:
    containers = await collect_containers(
        socket_path=args.socket_path,
        timeout=args.timeout,
        limit=args.limit,
    )
    emit_models(containers, json_output=args.json, plain=args.plain, render=_render_containers)


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

    running = sum(1 for container in containers if container.state.lower() == "running")
    print_insight(f"Found {len(containers)} containers, {running} currently running.")

    print_section(1, "Container list", "Each row is one Docker container on this server.")
    print_data_table(
        CONTAINER_COLUMNS,
        [
            [
                container.container_name,
                format_state(container.state),
                container.image_name,
                format_optional(container.compose_project_name, fallback="—"),
                ", ".join(str(port) for port in container.published_ports) or "—",
            ]
            for container in containers
        ],
    )
    print_column_guide(CONTAINER_COLUMNS)


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
