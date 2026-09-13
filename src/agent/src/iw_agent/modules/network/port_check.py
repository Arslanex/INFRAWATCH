from __future__ import annotations

from iw_agent.modules.network.collector import collect_listening_ports
from iw_agent.modules.network.schemas import ListeningPort, PortCheckResult

PUBLIC_BIND_ADDRESSES = frozenset({"0.0.0.0", "*", "::", "[::]"})


async def check_ports(ports: list[int]) -> list[PortCheckResult]:
    if not ports:
        return []

    listening = await collect_listening_ports()
    by_port: dict[int, list[ListeningPort]] = {}
    for entry in listening:
        by_port.setdefault(entry.port_number, []).append(entry)

    results: list[PortCheckResult] = []
    for port in sorted(set(ports)):
        listeners = by_port.get(port, [])
        if not listeners:
            results.append(
                PortCheckResult(
                    port=port,
                    available=True,
                    note="no listener on this port",
                )
            )
            continue

        public_listeners = [
            entry
            for entry in listeners
            if _is_public_bind(entry.listen_address)
        ]
        if public_listeners:
            entry = public_listeners[0]
            owner = _listener_label(entry)
            results.append(
                PortCheckResult(
                    port=port,
                    available=False,
                    listener=owner,
                    owner_label=entry.owner_label,
                    note="port is already in use",
                )
            )
            continue

        entry = listeners[0]
        owner = _listener_label(entry)
        results.append(
            PortCheckResult(
                port=port,
                available=True,
                listener=owner,
                owner_label=entry.owner_label,
                note="bound to localhost only — OK for backend services",
            )
        )
    return results


def _is_public_bind(address: str) -> bool:
    normalized = address.strip().lower()
    if normalized in PUBLIC_BIND_ADDRESSES:
        return True
    return normalized.startswith("::") and normalized not in {"::1", "[::1]"}


def _listener_label(entry: ListeningPort) -> str:
    parts = [entry.protocol, str(entry.port_number), entry.listen_address]
    if entry.process_name:
        parts.append(entry.process_name)
    elif entry.owner_label:
        parts.append(entry.owner_label)
    return " · ".join(parts)
