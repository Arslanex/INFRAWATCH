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
    emit_models(
        ports,
        json_output=args.json,
        plain=args.plain,
        render=lambda data: _render_ports(data, standalone=True),
    )


async def run_connections(args: argparse.Namespace) -> None:
    connections = await collect_outbound_connections(limit=args.limit)
    emit_models(
        connections,
        json_output=args.json,
        plain=args.plain,
        render=lambda data: _render_connections(data, standalone=True),
    )


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


def _ports_summary(ports: list[ListeningPort]) -> str:
    if not ports:
        return "No open ports were detected on this server."
    tcp_count = sum(1 for port in ports if port.protocol.lower() == "tcp")
    udp_count = len(ports) - tcp_count
    programs = {port.process_name for port in ports if port.process_name}
    notable = sorted(
        {
            str(port.port_number)
            for port in ports
            if port.port_number in {22, 80, 443, 3306, 5432, 6379, 8080}
        }
    )
    parts = [f"Found {len(ports)} open port(s): {tcp_count} TCP, {udp_count} UDP."]
    if notable:
        parts.append(f"Common services: {', '.join(notable)}.")
    if programs:
        parts.append(f"Used by {len(programs)} different program(s).")
    return " ".join(parts)


def _connections_summary(connections: list[OutboundConnection]) -> str:
    if not connections:
        return "No outbound connections are active right now."
    total_links = sum(connection.connection_count for connection in connections)
    programs = {connection.process_name for connection in connections if connection.process_name}
    top = connections[0]
    parts = [
        f"Found {len(connections)} destination(s) with {total_links} open connection(s) in total."
    ]
    if top.process_name:
        parts.append(
            f"Most active: {top.process_name} → {top.remote_address}:{top.remote_port} "
            f"({top.connection_count} link(s))."
        )
    if programs:
        parts.append(f"Involves {len(programs)} program(s).")
    return " ".join(parts)


def _render_ports(ports: list[ListeningPort], *, step: int = 1, standalone: bool = False) -> None:
    if standalone:
        print_report(
            "Open ports",
            "Services on this server that accept incoming connections.",
        )
        print_insight(_ports_summary(ports))
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


def _render_connections(
    connections: list[OutboundConnection],
    *,
    step: int = 1,
    standalone: bool = False,
) -> None:
    if standalone:
        print_report(
            "Outbound connections",
            "Programs on this server connecting to other machines.",
        )
        print_insight(_connections_summary(connections))
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
