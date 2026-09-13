from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    print_heading,
    print_result_count,
    print_table,
)
from iw_agent.cli.parser import add_limit_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.network.collector import (
    collect_listening_ports,
    collect_network_snapshot,
    collect_outbound_connections,
)
from iw_agent.modules.network.schemas import ListeningPort, NetworkSnapshot, OutboundConnection


async def run_network(args: argparse.Namespace) -> None:
    snapshot = await collect_network_snapshot(outbound_limit=args.limit)
    emit_models(snapshot, json_output=args.json, render=_render_network)


async def run_ports(args: argparse.Namespace) -> None:
    ports = await collect_listening_ports()
    emit_models(ports, json_output=args.json, render=_render_ports)


async def run_connections(args: argparse.Namespace) -> None:
    connections = await collect_outbound_connections(limit=args.limit)
    emit_models(connections, json_output=args.json, render=_render_connections)


def _render_network(snapshot: NetworkSnapshot) -> None:
    print_heading("Listening ports")
    _render_ports(snapshot.listening_ports)
    print_heading("Outbound connections")
    _render_connections(snapshot.outbound_connections)


def _render_ports(ports: list[ListeningPort]) -> None:
    print_result_count("listening port", len(ports))
    print_table(
        ["PROTO", "PORT", "ADDRESS", "PID", "PROCESS"],
        [
            [
                port.protocol,
                str(port.port_number),
                port.listen_address,
                format_optional(port.pid),
                format_optional(port.process_name),
            ]
            for port in sorted(ports, key=lambda row: (row.protocol, row.port_number))
        ],
        widths=[6, 6, 20, 8, 16],
    )


def _render_connections(connections: list[OutboundConnection]) -> None:
    print_result_count("outbound connection", len(connections))
    print_table(
        ["PID", "PROCESS", "REMOTE", "PORT", "COUNT"],
        [
            [
                format_optional(connection.pid),
                format_optional(connection.process_name),
                connection.remote_address,
                str(connection.remote_port),
                str(connection.connection_count),
            ]
            for connection in connections
        ],
        widths=[8, 16, 18, 8, 6],
    )


def _configure_network(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=20, help_text="max outbound rows")


def _configure_connections(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=20, help_text="max rows")


COMMAND_SPECS = [
    CliCommandSpec("network", "ports and outbound connections", run_network, _configure_network),
    CliCommandSpec("ports", "listening ports", run_ports),
    CliCommandSpec("connections", "outbound connections", run_connections, _configure_connections),
]
