from __future__ import annotations

import psutil

from iw_agent.core.exceptions import (
    NetworkAccessDeniedError,
    NetworkReadError,
    ProcessAccessDeniedError,
    ProcessReadError,
)


def read_inet_connections() -> list:
    try:
        return psutil.net_connections(kind="inet")
    except psutil.AccessDenied as exc:
        raise NetworkAccessDeniedError() from exc
    except OSError as exc:
        raise NetworkReadError(f"net_connections failed: {exc}") from exc


def iter_processes(attrs: list[str]):
    try:
        return psutil.process_iter(attrs)
    except psutil.AccessDenied as exc:
        raise ProcessAccessDeniedError() from exc
    except OSError as exc:
        raise ProcessReadError(f"process_iter failed: {exc}") from exc


def normalize_ip_address(ip: str) -> str:
    return ip.split("%", 1)[0]


def process_names_by_pid(pids: set[int]) -> dict[int, str]:
    names_by_pid: dict[int, str] = {}
    if not pids:
        return names_by_pid

    for process_entry in psutil.process_iter(["pid", "name"]):
        try:
            pid = process_entry.info["pid"]
            if pid in pids:
                names_by_pid[pid] = process_entry.info["name"] or ""
        except psutil.Error:
            continue

    return names_by_pid
