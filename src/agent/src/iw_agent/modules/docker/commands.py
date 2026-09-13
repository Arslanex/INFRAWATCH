from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    print_result_count,
    print_table,
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


async def run_containers(args: argparse.Namespace) -> None:
    containers = await collect_containers(
        socket_path=args.socket_path,
        timeout=args.timeout,
        limit=args.limit,
    )
    emit_models(containers, json_output=args.json, render=_render_containers)


def _render_containers(containers: list[Container]) -> None:
    print_result_count("container", len(containers))
    print_table(
        ["STATE", "NAME", "IMAGE", "COMPOSE", "PORTS"],
        [
            [
                container.state,
                container.container_name,
                container.image_name,
                format_optional(container.compose_project_name),
                ", ".join(str(port) for port in container.published_ports) or "-",
            ]
            for container in containers
        ],
        widths=[10, 22, 28, 14, 24],
    )


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
