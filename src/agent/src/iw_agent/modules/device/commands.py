from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    DIM,
    _c,
    _reset,
    emit_models,
    format_cpu_core_grid,
    format_disk_bars,
    format_load_panel,
    format_memory_bar,
    format_optional,
    format_bytes,
    print_empty,
    print_insight,
    print_labeled_block,
    print_labeled_rows,
    print_report,
    print_section,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.device.collector import (
    collect_device_metrics,
    collect_device_snapshot,
    collect_disk_volumes,
)
from iw_agent.modules.device.schemas import DeviceMetrics, DeviceSnapshot, DiskVolume

_WORKLOAD_LABEL_WIDTH = 17


async def run_device(args: argparse.Namespace) -> None:
    snapshot = await collect_device_snapshot()
    emit_models(snapshot, json_output=args.json, plain=args.plain, render=_render_device)


async def run_metrics(args: argparse.Namespace) -> None:
    metrics = await collect_device_metrics()
    emit_models(
        metrics,
        json_output=args.json,
        plain=args.plain,
        render=lambda data: _render_metrics(data, standalone=True, dashboard=True),
    )


async def run_disks(args: argparse.Namespace) -> None:
    disks = await collect_disk_volumes()
    emit_models(
        disks,
        json_output=args.json,
        plain=args.plain,
        render=lambda data: _render_disks(data, standalone=True, step=1),
    )


def _device_summary(snapshot: DeviceSnapshot) -> str:
    system = snapshot.system
    metrics = snapshot.metrics
    parts = [
        f"{system.hostname} runs {system.operating_system}"
        f"{f' {system.os_release}' if system.os_release else ''}."
    ]

    if metrics.cpu_percent is not None:
        parts.append(f"CPU {metrics.cpu_percent:.0f}%")
    if metrics.memory_used_bytes is not None and metrics.memory_total_bytes:
        mem_pct = (metrics.memory_used_bytes / metrics.memory_total_bytes) * 100
        parts.append(f"RAM {mem_pct:.0f}%")
    if metrics.load_1 is not None:
        parts.append(f"load {metrics.load_1:.2f}")

    return " · ".join(parts)


def _metrics_summary(metrics: DeviceMetrics) -> str:
    cpu = f"{metrics.cpu_percent:.0f}%" if metrics.cpu_percent is not None else "unknown"
    if metrics.memory_used_bytes is not None and metrics.memory_total_bytes:
        mem_pct = (metrics.memory_used_bytes / metrics.memory_total_bytes) * 100
        memory = f"{mem_pct:.0f}% RAM used"
    else:
        memory = "memory unknown"
    load = f"load {metrics.load_1:.2f}" if metrics.load_1 is not None else "load unknown"
    return f"CPU at {cpu}, {memory}, {load}."


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
        return f"Found {len(disks)} disk(s). Warning: {names} is almost full."
    return f"Found {len(disks)} disk partition(s); none are critically full."


def _cpu_percents(metrics: DeviceMetrics) -> list[float]:
    per_core = metrics.cpu_percent_per_core or []
    if not per_core and metrics.cpu_percent is not None and metrics.cpu_count_logical:
        return [metrics.cpu_percent] * metrics.cpu_count_logical
    return per_core


def _render_device(snapshot: DeviceSnapshot) -> None:
    system = snapshot.system
    metrics = snapshot.metrics

    print_report(
        "Server overview",
        "A simple health check of this computer.",
    )
    print_insight(_device_summary(snapshot))

    print_section(1, "About this computer", "Who this server is and when it last restarted.")
    print_labeled_rows(
        [
            ("Computer name", system.hostname),
            ("Operating system", f"{system.operating_system} ({format_optional(system.machine)})"),
            ("Last restart", format_optional(system.boot_time)),
        ]
    )

    _render_metrics(metrics, step=2, dashboard=True)
    _render_disks(snapshot.disks, step=3)


def _render_metrics(
    metrics: DeviceMetrics,
    *,
    step: int = 1,
    standalone: bool = False,
    dashboard: bool = False,
) -> None:
    if standalone:
        print_report(
            "Server workload",
            "How busy the processor, memory, and system are right now.",
        )
        print_insight(_metrics_summary(metrics))

    print_section(step, "Current workload", "How busy the server is right now.")

    label_width = _WORKLOAD_LABEL_WIDTH if dashboard else None
    per_core = _cpu_percents(metrics)

    print_labeled_block(
        "Processor (CPU)",
        format_cpu_core_grid(per_core),
        label_width=label_width,
    )
    print_labeled_block(
        "Memory (RAM)",
        format_memory_bar(metrics.memory_used_bytes, metrics.memory_total_bytes),
        label_width=label_width,
    )
    print_labeled_block(
        "System load",
        format_load_panel(
            metrics.load_1,
            metrics.load_5,
            metrics.load_15,
            metrics.cpu_count_logical,
        ),
        label_width=label_width,
    )
    print_labeled_block(
        "Network traffic",
        [
            f"received {format_bytes(metrics.net_rx_bytes)}, "
            f"sent {format_bytes(metrics.net_tx_bytes)}"
            f"  {_c(DIM)}(total since boot){_reset()}",
        ],
        label_width=label_width,
    )


def _render_disks(
    disks: list[DiskVolume],
    *,
    step: int = 1,
    standalone: bool = False,
) -> None:
    if standalone:
        print_report(
            "Storage space",
            "How much room is left on each disk partition.",
        )
        print_insight(_disks_summary(disks))

    print_section(step, "Storage space", "How full each disk partition is.")
    if not disks:
        print_empty(
            "no disks found",
            "The agent could not read disk usage.",
            "check permissions or run with sudo.",
        )
        return

    print_labeled_block(
        "Disk partitions",
        format_disk_bars(
            [(disk.mount_point, disk.used_bytes, disk.total_bytes) for disk in disks]
        ),
    )


COMMAND_SPECS = [
    CliCommandSpec("device", "full device overview", run_device),
    CliCommandSpec("metrics", "cpu, memory, and load", run_metrics),
    CliCommandSpec("disks", "disk usage by mount point", run_disks),
]
