from __future__ import annotations

import platform
import socket
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

import psutil

from iw_agent.core._thread import read
from iw_agent.core.exceptions import (
    DeviceDiskUnreadableError,
    DeviceMetricUnavailableError,
)
from iw_agent.core.logger import logger
from iw_agent.modules.device.schemas import (
    DeviceMetrics,
    DeviceSnapshot,
    DeviceSystem,
    DiskVolume,
)

T = TypeVar("T")


async def collect_device_snapshot() -> DeviceSnapshot:
    return await read(_collect_device_snapshot)


async def collect_device_metrics() -> DeviceMetrics:
    return await read(_read_device_metrics)


async def collect_disk_volumes() -> list[DiskVolume]:
    return await read(_collect_disk_volumes)


def _collect_disk_volumes() -> list[DiskVolume]:
    disks = _read_disk_volumes()
    logger.debug("collected %d disk volumes", len(disks))
    return disks


def _collect_device_snapshot() -> DeviceSnapshot:
    snapshot = DeviceSnapshot(
        system=_read_device_system(),
        metrics=_read_device_metrics(),
        disks=_read_disk_volumes(),
    )

    logger.debug(
        "collected device snapshot for %s (%d disks)",
        snapshot.system.hostname,
        len(snapshot.disks),
    )
    return snapshot


def _read_device_system() -> DeviceSystem:
    boot_time = _safe_read(lambda: psutil.boot_time())

    return DeviceSystem(
        hostname=socket.gethostname(),
        operating_system=platform.system(),
        os_release=platform.release() or None,
        os_version=platform.version() or None,
        machine=platform.machine() or None,
        boot_time=(
            datetime.fromtimestamp(boot_time, timezone.utc)
            if boot_time is not None
            else None
        ),
    )


def _read_device_metrics() -> DeviceMetrics:
    load_averages = _read_load_averages()
    network_counters = _read_network_counters()

    return DeviceMetrics(
        cpu_percent=_safe_read(lambda: psutil.cpu_percent(interval=None)),
        cpu_count_logical=_safe_read(lambda: psutil.cpu_count(logical=True)),
        cpu_count_physical=_safe_read(lambda: psutil.cpu_count(logical=False)),
        memory_used_bytes=_safe_read(lambda: psutil.virtual_memory().used),
        memory_total_bytes=_safe_read(lambda: psutil.virtual_memory().total),
        load_1=load_averages["load_1"],
        load_5=load_averages["load_5"],
        load_15=load_averages["load_15"],
        net_rx_bytes=network_counters["net_rx_bytes"],
        net_tx_bytes=network_counters["net_tx_bytes"],
    )


def _read_disk_volumes() -> list[DiskVolume]:
    disk_volumes: list[DiskVolume] = []

    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (PermissionError, OSError) as exc:
            logger.debug(
                "%s",
                DeviceDiskUnreadableError(
                    f"{partition.mountpoint}: {exc}"
                ),
            )
            continue

        disk_volumes.append(
            DiskVolume(
                mount_point=partition.mountpoint,
                device=partition.device,
                filesystem=partition.fstype or None,
                used_bytes=usage.used,
                total_bytes=usage.total,
            )
        )

    return disk_volumes


def _read_load_averages() -> dict[str, float | None]:
    try:
        load_1, load_5, load_15 = psutil.getloadavg()
    except (OSError, AttributeError):
        return {"load_1": None, "load_5": None, "load_15": None}

    return {"load_1": load_1, "load_5": load_5, "load_15": load_15}


def _read_network_counters() -> dict[str, int | None]:
    counters = _safe_read(psutil.net_io_counters)
    if counters is None:
        return {"net_rx_bytes": None, "net_tx_bytes": None}

    return {
        "net_rx_bytes": counters.bytes_recv,
        "net_tx_bytes": counters.bytes_sent,
    }


def _safe_read(read_value: Callable[[], T]) -> T | None:
    try:
        return read_value()
    except (psutil.Error, OSError) as exc:
        logger.debug("%s", DeviceMetricUnavailableError(str(exc)))
        return None


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        snapshot = await collect_device_snapshot()
        system = snapshot.system
        metrics = snapshot.metrics

        print(f"hostname={system.hostname}")
        print(
            f"os={system.operating_system} "
            f"release={system.os_release or '-'} "
            f"machine={system.machine or '-'}"
        )
        print(f"boot_time={system.boot_time.isoformat() if system.boot_time else '-'}")

        memory_used_gb = (metrics.memory_used_bytes or 0) / (1024 ** 3)
        memory_total_gb = (metrics.memory_total_bytes or 0) / (1024 ** 3)
        print(
            f"cpu={metrics.cpu_percent if metrics.cpu_percent is not None else '-'}% "
            f"cores={metrics.cpu_count_logical or '-'}/"
            f"{metrics.cpu_count_physical or '-'} "
            f"mem={memory_used_gb:.1f}/{memory_total_gb:.1f} GB"
        )
        print(
            f"load={metrics.load_1}/{metrics.load_5}/{metrics.load_15} "
            f"net_rx={metrics.net_rx_bytes} net_tx={metrics.net_tx_bytes}"
        )

        print(f"\nfound {len(snapshot.disks)} disk volumes\n")
        for disk in snapshot.disks:
            used_gb = disk.used_bytes / (1024 ** 3)
            total_gb = disk.total_bytes / (1024 ** 3)
            print(
                f"{disk.mount_point:<20} "
                f"{disk.device:<16} "
                f"{disk.filesystem or '-':<8} "
                f"{used_gb:6.1f}/{total_gb:6.1f} GB"
            )

    asyncio.run(_main())
