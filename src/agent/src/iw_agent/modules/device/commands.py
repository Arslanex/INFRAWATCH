from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    DIM,
    _c,
    _reset,
    emit_models,
    format_bytes,
    format_cpu_core_meters,
    format_disk_meters,
    format_fields,
    format_load_meter_line,
    format_memory_meter_line,
    format_optional,
    print_empty,
    print_info_box,
    print_insight,
    print_report,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.device.collector import (
    collect_device_metrics,
    collect_device_snapshot,
    collect_disk_volumes,
)
from iw_agent.modules.device.schemas import DeviceMetrics, DeviceSnapshot, DeviceSystem, DiskVolume


async def run_device(args: argparse.Namespace) -> None:
    snapshot = await collect_device_snapshot()
    emit_models(snapshot, json_output=args.json, plain=args.plain, render=_render_device)


async def run_metrics(args: argparse.Namespace) -> None:
    metrics = await collect_device_metrics()
    emit_models(
        metrics,
        json_output=args.json,
        plain=args.plain,
        render=lambda data: _render_metrics(data, standalone=True),
    )


async def run_disks(args: argparse.Namespace) -> None:
    disks = await collect_disk_volumes()
    emit_models(
        disks,
        json_output=args.json,
        plain=args.plain,
        render=lambda data: _render_disks(data, standalone=True),
    )


def _workload_summary(metrics: DeviceMetrics) -> str:
    parts: list[str] = []
    if metrics.cpu_percent is not None:
        parts.append(f"CPU {metrics.cpu_percent:.0f}%")
    if metrics.memory_used_bytes is not None and metrics.memory_total_bytes:
        mem_pct = (metrics.memory_used_bytes / metrics.memory_total_bytes) * 100
        parts.append(f"RAM {mem_pct:.0f}%")
    if metrics.load_1 is not None:
        parts.append(f"load {metrics.load_1:.2f}")
    return " · ".join(parts) if parts else "Workload unknown"


def _device_summary(snapshot: DeviceSnapshot) -> str:
    return f"{snapshot.system.hostname} · {_workload_summary(snapshot.metrics)}"


def _disks_summary(disks: list[DiskVolume]) -> str:
    if not disks:
        return "No disk usage information could be read."
    full = [
        disk
        for disk in disks
        if disk.total_bytes > 0 and (disk.used_bytes / disk.total_bytes) >= 0.9
    ]
    if full:
        names = ", ".join(disk.mount_point for disk in full[:3])
        return f"{len(disks)} disk(s) · warning: {names} almost full"
    return f"{len(disks)} disk(s) · all OK"


def _cpu_percents(metrics: DeviceMetrics) -> list[float]:
    per_core = metrics.cpu_percent_per_core or []
    if not per_core and metrics.cpu_percent is not None and metrics.cpu_count_logical:
        return [metrics.cpu_percent] * metrics.cpu_count_logical
    return per_core


def _render_system_info(system: DeviceSystem) -> None:
    print_info_box(
        title="System",
        hint="identity",
        lines=format_fields(
            [
                ("Host", system.hostname),
                (
                    "OS",
                    f"{system.operating_system} {_c(DIM)}({format_optional(system.machine)}){_reset()}",
                ),
                ("Reboot", format_optional(system.boot_time)),
            ]
        ),
    )


def _render_workload(metrics: DeviceMetrics) -> None:
    print_info_box(
        title="CPU",
        hint="usage bars — green · yellow · red",
        lines=format_cpu_core_meters(_cpu_percents(metrics)),
    )

    print_info_box(
        title="Memory",
        hint="RAM used right now",
        lines=[format_memory_meter_line(metrics.memory_used_bytes, metrics.memory_total_bytes)],
    )

    print_info_box(
        title="Load",
        hint="how busy the process queue is",
        lines=[
            format_load_meter_line(
                metrics.load_1,
                metrics.load_5,
                metrics.load_15,
                metrics.cpu_count_logical,
            )
        ],
    )

    print_info_box(
        title="Network",
        hint="traffic since last boot",
        lines=format_fields(
            [
                (
                    "Traffic",
                    f"received {format_bytes(metrics.net_rx_bytes)}"
                    f" · sent {format_bytes(metrics.net_tx_bytes)}",
                )
            ]
        ),
    )


def _render_device(snapshot: DeviceSnapshot) -> None:
    system = snapshot.system

    print_report(
        "Server overview",
        f"{system.hostname} · {system.operating_system}",
    )
    print_insight(_device_summary(snapshot))

    _render_system_info(system)
    _render_workload(snapshot.metrics)
    _render_disks(snapshot.disks, embedded=True)


def _render_metrics(metrics: DeviceMetrics, *, standalone: bool = False) -> None:
    if standalone:
        print_report(
            "Server workload",
            "Processor, memory, and system load.",
        )
        print_insight(_workload_summary(metrics))

    _render_workload(metrics)


def _render_disks(
    disks: list[DiskVolume],
    *,
    standalone: bool = False,
    embedded: bool = False,
) -> None:
    if standalone:
        print_report(
            "Storage space",
            "Disk partitions on this server.",
        )
        print_insight(_disks_summary(disks))

    if not disks:
        print_empty(
            "no disks found",
            "The agent could not read disk usage.",
            "check permissions or run with sudo.",
        )
        return

    print_info_box(
        title="Disks",
        hint="fill level — green · yellow · red",
        lines=format_disk_meters(
            [(disk.mount_point, disk.used_bytes, disk.total_bytes) for disk in disks],
            label_width=12,
        ),
    )


COMMAND_SPECS = [
    CliCommandSpec("device", "full device overview", run_device),
    CliCommandSpec("metrics", "cpu, memory, and load", run_metrics),
    CliCommandSpec("disks", "disk usage by mount point", run_disks),
]
