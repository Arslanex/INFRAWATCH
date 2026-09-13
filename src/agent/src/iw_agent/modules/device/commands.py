from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_cpu_line,
    format_load_line,
    format_optional,
    format_usage_ratio,
    format_bytes,
    print_column_guide,
    print_data_table,
    print_insight,
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


async def run_device(args: argparse.Namespace) -> None:
    snapshot = await collect_device_snapshot()
    emit_models(snapshot, json_output=args.json, plain=args.plain, render=_render_device)


async def run_metrics(args: argparse.Namespace) -> None:
    metrics = await collect_device_metrics()
    emit_models(metrics, json_output=args.json, plain=args.plain, render=_render_metrics)


async def run_disks(args: argparse.Namespace) -> None:
    disks = await collect_disk_volumes()
    emit_models(disks, json_output=args.json, plain=args.plain, render=_render_disks)


def _render_device(snapshot: DeviceSnapshot) -> None:
    system = snapshot.system
    metrics = snapshot.metrics

    print_report(
        "Server overview",
        "A simple health check of this computer.",
    )
    print_insight(
        f"This machine is called {system.hostname} and is running "
        f"{system.operating_system} {format_optional(system.os_release, fallback='')}."
    )

    print_section(1, "About this computer", "Who this server is and when it last restarted.")
    print_labeled_rows(
        [
            ("Computer name", system.hostname),
            ("Operating system", f"{system.operating_system} ({format_optional(system.machine)})"),
            ("Last restart", format_optional(system.boot_time)),
        ]
    )

    _render_metrics(metrics, step=2)
    _render_disks(snapshot.disks, step=3)


def _render_metrics(metrics: DeviceMetrics, *, step: int = 1) -> None:
    print_section(step, "Current workload", "How busy the server is right now.")
    print_labeled_rows(
        [
            ("Processor (CPU)", format_cpu_line(metrics.cpu_percent, metrics.cpu_count_logical)),
            ("Memory (RAM)", format_usage_ratio(metrics.memory_used_bytes, metrics.memory_total_bytes)),
            ("System load", format_load_line(metrics.load_1, metrics.load_5, metrics.load_15)),
            (
                "Network traffic (total since boot)",
                f"received {format_bytes(metrics.net_rx_bytes)}, sent {format_bytes(metrics.net_tx_bytes)}",
            ),
        ]
    )


def _render_disks(disks: list[DiskVolume], *, step: int = 1) -> None:
    disk_columns = [
        ("Folder", "where data is stored on the server"),
        ("Used / total", "how much space is used"),
        ("Status", "how full the disk is"),
    ]
    print_section(step, "Storage space", "How full each disk partition is.")
    if not disks:
        from iw_agent.cli.output import print_empty

        print_empty(
            "no disks found",
            "The agent could not read disk usage.",
            "check permissions or run with sudo.",
        )
        return

    print_data_table(
        disk_columns,
        [
            [
                disk.mount_point,
                f"{format_bytes(disk.used_bytes)} / {format_bytes(disk.total_bytes)}",
                _disk_status(disk.used_bytes, disk.total_bytes),
            ]
            for disk in disks
        ],
    )
    print_column_guide(disk_columns)


def _disk_status(used_bytes: int, total_bytes: int) -> str:
    if total_bytes <= 0:
        return "unknown"
    percent = (used_bytes / total_bytes) * 100
    if percent >= 90:
        return "critically full"
    if percent >= 75:
        return "getting full"
    return "ok"


COMMAND_SPECS = [
    CliCommandSpec("device", "full device overview", run_device),
    CliCommandSpec("metrics", "cpu, memory, and load", run_metrics),
    CliCommandSpec("disks", "disk usage by mount point", run_disks),
]
