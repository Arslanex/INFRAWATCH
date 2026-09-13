from __future__ import annotations

import socket
from collections import Counter

import psutil

from iw_agent.core._thread import read
from iw_agent.core.logger import logger
from iw_agent.core.psutil_helpers import (
    normalize_ip_address,
    process_names_by_pid,
    read_inet_connections,
)
from iw_agent.modules.network.schemas import (
    ListeningPort,
    NetworkSnapshot,
    OutboundConnection,
)

PROTOCOL_BY_SOCKET_TYPE = {
    socket.SOCK_STREAM: "tcp",
    socket.SOCK_DGRAM: "udp",
}

DEFAULT_OUTBOUND_LIMIT = 200


async def collect_network_snapshot(
    outbound_limit: int = DEFAULT_OUTBOUND_LIMIT,
) -> NetworkSnapshot:
    return await read(_collect_network_snapshot, outbound_limit)


async def collect_listening_ports() -> list[ListeningPort]:
    snapshot = await collect_network_snapshot(outbound_limit=0)
    return snapshot.listening_ports


async def collect_outbound_connections(
    limit: int = DEFAULT_OUTBOUND_LIMIT,
) -> list[OutboundConnection]:
    snapshot = await collect_network_snapshot(outbound_limit=limit)
    return snapshot.outbound_connections


def _collect_network_snapshot(outbound_limit: int) -> NetworkSnapshot:
    # 1. Tüm inet bağlantılarını tek seferde oku
    connections = read_inet_connections()

    # 2. Dinleyen ve giden bağlantıları ayıkla
    listening_connections = _listening_connections(connections)
    destination_counts = (
        _outbound_destination_counts(connections)
        if outbound_limit > 0
        else Counter()
    )

    # 3. Process isimlerini tek seferde çöz
    pids = {
        connection.pid
        for connection, _ in listening_connections
        if connection.pid is not None
    }
    pids.update(
        pid for pid, _, _ in destination_counts if pid is not None
    )
    names_by_pid = process_names_by_pid(pids)

    listening_ports = _build_listening_ports(listening_connections, names_by_pid)
    outbound_connections = _build_outbound_connections(
        destination_counts,
        names_by_pid,
        outbound_limit,
    )

    logger.debug(
        "collected network snapshot: %d listening ports, %d outbound connections",
        len(listening_ports),
        len(outbound_connections),
    )

    return NetworkSnapshot(
        listening_ports=listening_ports,
        outbound_connections=outbound_connections,
    )


def _listening_connections(connections) -> list[tuple[object, str]]:
    listening_connections: list[tuple[object, str]] = []

    for connection in connections:
        protocol = _socket_protocol(connection)
        if protocol is None:
            continue
        if not connection.laddr:
            continue
        if not _is_listening(connection, protocol):
            continue
        listening_connections.append((connection, protocol))

    return listening_connections


def _build_listening_ports(
    listening_connections: list[tuple[object, str]],
    names_by_pid: dict[int, str],
) -> list[ListeningPort]:
    listening_ports: list[ListeningPort] = []
    for connection, protocol in listening_connections:
        listening_ports.append(
            ListeningPort(
                protocol=protocol,
                port_number=connection.laddr.port,
                listen_address=normalize_ip_address(connection.laddr.ip),
                pid=connection.pid,
                process_name=(
                    names_by_pid.get(connection.pid)
                    if connection.pid is not None
                    else None
                ),
            )
        )

    return listening_ports


def _outbound_destination_counts(
    connections,
) -> Counter[tuple[int | None, str, int]]:
    listening_port_numbers = {
        connection.laddr.port
        for connection in connections
        if connection.laddr and connection.status == psutil.CONN_LISTEN
    }

    destination_counts: Counter[tuple[int | None, str, int]] = Counter()

    for connection in connections:
        protocol = _socket_protocol(connection)
        if not _is_outbound_connection(
            connection,
            listening_port_numbers,
            protocol,
        ):
            continue

        destination_counts[
            (
                connection.pid,
                normalize_ip_address(connection.raddr.ip),
                connection.raddr.port,
            )
        ] += 1

    return destination_counts


def _build_outbound_connections(
    destination_counts: Counter[tuple[int | None, str, int]],
    names_by_pid: dict[int, str],
    limit: int,
) -> list[OutboundConnection]:
    outbound_connections = [
        OutboundConnection(
            pid=pid,
            process_name=(
                names_by_pid.get(pid)
                if pid is not None
                else None
            ),
            remote_address=remote_address,
            remote_port=remote_port,
            connection_count=connection_count,
        )
        for (pid, remote_address, remote_port), connection_count in destination_counts.most_common(
            limit
        )
    ]

    if len(destination_counts) > limit:
        logger.debug(
            "outbound connections capped at %d of %d destinations",
            limit,
            len(destination_counts),
        )

    return outbound_connections


def _socket_protocol(connection) -> str | None:
    return PROTOCOL_BY_SOCKET_TYPE.get(connection.type)


def _is_outbound_connection(
    connection,
    listening_port_numbers: set[int],
    protocol: str | None,
) -> bool:
    if protocol is None or not connection.raddr or not connection.laddr:
        return False
    if connection.laddr.port in listening_port_numbers:
        return False

    if protocol == "tcp":
        return connection.status in {
            psutil.CONN_ESTABLISHED,
            psutil.CONN_SYN_SENT,
        }

    if protocol == "udp":
        return connection.status in {
            psutil.CONN_NONE,
            psutil.CONN_ESTABLISHED,
            "",
        }

    return False


def _is_listening(connection, protocol: str) -> bool:
    if protocol == "tcp":
        return connection.status == psutil.CONN_LISTEN
    return not connection.raddr


if __name__ == "__main__":
    import asyncio
    import sys

    from iw_agent.core.exceptions import NetworkError

    async def _main() -> None:
        outbound_limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20

        try:
            snapshot = await collect_network_snapshot(outbound_limit=outbound_limit)
        except NetworkError as exc:
            print(f"error: {exc}")
            raise SystemExit(1) from exc

        listening_ports = sorted(
            snapshot.listening_ports,
            key=lambda port: (port.protocol, port.port_number, port.listen_address),
        )
        print(
            f"found {len(listening_ports)} listening ports, "
            f"{len(snapshot.outbound_connections)} outbound connections\n"
        )

        print("=== listening ports ===")
        for listening_port in listening_ports:
            pid = listening_port.pid if listening_port.pid is not None else "-"
            process_name = listening_port.process_name or "-"
            print(
                f"{listening_port.protocol:4} {listening_port.port_number:5} "
                f"{listening_port.listen_address:39} "
                f"pid={pid:<6} {process_name}"
            )

        print("\n=== outbound connections ===")
        for outbound_connection in snapshot.outbound_connections:
            pid = (
                outbound_connection.pid
                if outbound_connection.pid is not None
                else "-"
            )
            process_name = outbound_connection.process_name or "-"
            print(
                f"pid={pid:<6} {process_name:<16} "
                f"{outbound_connection.remote_address}:"
                f"{outbound_connection.remote_port:<6} "
                f"count={outbound_connection.connection_count}"
            )

    asyncio.run(_main())
