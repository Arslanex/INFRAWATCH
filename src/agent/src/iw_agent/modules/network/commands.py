from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    print_column_guide,
    print_data_table,
    print_empty,
    print_insight,
    print_report,
    print_section,
)
from iw_agent.cli.parser import add_limit_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.network.collector import (
    collect_listening_ports,
    collect_network_snapshot,
    collect_outbound_connections,
)
from iw_agent.modules.network.schemas import ListeningPort, NetworkSnapshot, OutboundConnection

PORT_COLUMNS = [
    ("Port", "door number other computers use to connect"),
    ("Type", "usually tcp or udp"),
    ("Listening on", "network address that accepts connections"),
    ("Program", "software using this port"),
]

CONNECTION_COLUMNS = [
    ("Program", "software making the connection"),
    ("Connects to", "remote server address"),
    ("Port", "remote port number"),
    ("Links", "how many open connections to that target"),
]


async def run_network(args: argparse.Namespace) -> None:
    snapshot = await collect_network_snapshot(outbound_limit=args.limit)
    emit_models(snapshot, json_output=args.json, plain=args.plain, render=_render_network)


async def run_ports(args: argparse.Namespace) -> None:
    ports = await collect_listening_ports()
    emit_models(ports, json_output=args.json, plain=args.plain, render=_render_ports)


async def run_connections(args: argparse.Namespace) -> None:
    connections = await collect_outbound_connections(limit=args.limit)
    emit_models(connections, json_output=args.json, plain=args.plain, render=_render_connections)


def _render_network(snapshot: NetworkSnapshot) -> None:
    print_report(
        "Network activity",
        "Which programs accept connections and where this server connects out.",
    )
    print_insight(
        f"Found {len(snapshot.listening_ports)} open ports and "
        f"{len(snapshot.outbound_connections)} outbound connection groups."
    )
    _render_ports(snapshot.listening_ports, step=1)
    _render_connections(snapshot.outbound_connections, step=2)


def _render_ports(ports: list[ListeningPort], *, step: int = 1) -> None:
    print_section(step, "Open ports (listening)", "Services waiting for incoming connections.")
    if not ports:
        print_empty(
            "no open ports",
            "Nothing is listening, or the agent lacks permission to read network data.",
            "try: sudo iw ports",
        )
        return

    print_data_table(
        PORT_COLUMNS,
        [
            [
                str(port.port_number),
                port.protocol.upper(),
                port.listen_address,
                format_optional(port.process_name, fallback="unknown program"),
            ]
            for port in sorted(ports, key=lambda row: (row.protocol, row.port_number))
        ],
    )
    print_column_guide(PORT_COLUMNS)


def _render_connections(connections: list[OutboundConnection], *, step: int = 1) -> None:
    print_section(step, "Outbound connections", "Programs connecting to other servers.")
    if not connections:
        print_empty(
            "no outbound connections",
            "Either nothing is connected right now, or access was denied.",
            "try: sudo iw connections",
        )
        return

    print_data_table(
        CONNECTION_COLUMNS,
        [
            [
                format_optional(connection.process_name, fallback="unknown program"),
                connection.remote_address,
                str(connection.remote_port),
                str(connection.connection_count),
            ]
            for connection in connections
        ],
    )
    print_column_guide(CONNECTION_COLUMNS)


def _configure_network(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=20, help_text="max outbound rows")


def _configure_connections(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=20, help_text="max rows")


COMMAND_SPECS = [
    CliCommandSpec("network", "ports and outbound connections", run_network, _configure_network),
    CliCommandSpec("ports", "listening ports", run_ports),
    CliCommandSpec("connections", "outbound connections", run_connections, _configure_connections),
]
