from __future__ import annotations

import time
from datetime import datetime, timezone

import psutil

from iw_agent.core._thread import read
from iw_agent.core.logger import logger
from iw_agent.core.psutil_helpers import iter_processes
from iw_agent.modules.processes.cgroup import enrich_process_metadata
from iw_agent.modules.processes.schemas import Process


PSUTIL_PROCESS_ATTRS = [
    "pid",
    "ppid",
    "name",
    "username",
    "status",
    "memory_info",
    "create_time",
    "cmdline",
]

CPU_SAMPLE_SECONDS = 0.1


async def collect_processes(limit: int) -> list[Process]:
    return await read(_collect_processes, limit)


def _collect_processes(limit: int) -> list[Process]:
    # 1. Tüm process'leri oku
    process_entries = list(iter_processes(PSUTIL_PROCESS_ATTRS))

    # 2. CPU sayaçlarını hazırla (ilk okuma her zaman 0.0 döner)
    for process_entry in process_entries:
        try:
            process_entry.cpu_percent(interval=None)
        except (psutil.Error, psutil.NoSuchProcess):
            continue

    if CPU_SAMPLE_SECONDS > 0:
        time.sleep(CPU_SAMPLE_SECONDS)

    # 3. Process modellerine dönüştür
    processes: list[Process] = []
    for process_entry in process_entries:
        try:
            process_entry.info["cpu_percent"] = process_entry.cpu_percent(interval=None)
        except (psutil.Error, psutil.NoSuchProcess):
            process_entry.info["cpu_percent"] = None

        process = _process_from_psutil(process_entry)
        if process is not None:
            processes.append(process)

    # 4. CPU'ya göre sırala ve limitle
    processes.sort(
        key=lambda process: (
            _is_background_kernel_thread(process),
            -(process.cpu_percent or 0.0),
            -(process.memory_rss_bytes or 0),
        ),
    )
    processes = processes[:limit]

    # 5. Seçilen process'ler için ek bilgi oku
    for process in processes:
        enrich_process_metadata(process)

    logger.debug(
        "collected %d processes (limit=%d)",
        len(processes),
        limit,
    )
    return processes


def _is_background_kernel_thread(process: Process) -> bool:
    if (process.cpu_percent or 0.0) > 0.0:
        return False

    name = process.process_name
    if name in {"kthreadd", "ksoftirqd", "idle_inject"}:
        return True

    return name.startswith(("kworker", "rcu_", "pool_", "migration", "watchdog"))


def _process_from_psutil(process_entry: psutil.Process) -> Process | None:
    try:
        process_info = process_entry.info
    except psutil.Error:
        return None

    if process_info.get("pid") is None:
        return None

    memory_info = process_info.get("memory_info")
    create_time = process_info.get("create_time")
    command_parts = process_info.get("cmdline")

    return Process(
        pid=process_info["pid"],
        parent_pid=process_info.get("ppid"),
        process_name=process_info.get("name") or "",
        owner=process_info.get("username"),
        status=process_info.get("status"),
        cpu_percent=process_info.get("cpu_percent"),
        memory_rss_bytes=getattr(memory_info, "rss", None),
        started_at=(
            datetime.fromtimestamp(create_time, timezone.utc)
            if create_time
            else None
        ),
        command_line=" ".join(command_parts) if command_parts else None,
    )


if __name__ == "__main__":
    import asyncio
    import sys

    from iw_agent.core.exceptions import ProcessError

    async def _main() -> None:
        limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10

        try:
            processes = await collect_processes(limit)
        except ProcessError as exc:
            print(f"error: {exc}")
            raise SystemExit(1) from exc

        print(f"found {len(processes)} processes (limit={limit})\n")
        for process in processes:
            cpu = (
                f"{process.cpu_percent:.1f}"
                if process.cpu_percent is not None
                else "-"
            )
            memory_mb = (process.memory_rss_bytes or 0) / (1024 * 1024)
            cgroup_label = process.cgroup_owner or "-"
            print(
                f"pid={process.pid:<6} "
                f"cpu={cpu:>5}% "
                f"mem={memory_mb:7.1f}MB "
                f"{process.process_name:<16} "
                f"cgroup={process.cgroup_type or '-':<12} "
                f"owner={cgroup_label:<36} "
                f"{(process.command_line or '-')[:40]}"
            )

    asyncio.run(_main())
