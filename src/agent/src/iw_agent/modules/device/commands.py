from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_bytes,
    format_optional,
    format_percent,
    print_heading,
    print_result_count,
    print_summary,
    print_table,
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
    emit_models(snapshot, json_output=args.json, render=_render_device)


async def run_metrics(args: argparse.Namespace) -> None:
    metrics = await collect_device_metrics()
    emit_models(metrics, json_output=args.json, render=_render_metrics)


async def run_disks(args: argparse.Namespace) -> None:
    disks = await collect_disk_volumes()
    emit_models(disks, json_output=args.json, render=_render_disks)


def _render_device(snapshot: DeviceSnapshot) -> None:
    system = snapshot.system
    print_heading("Device")
    print_summary(
        [
            ("Host", system.hostname),
            (
                "OS",
                f"{system.operating_system} {format_optional(system.os_release)} "
                f"({format_optional(system.machine)})",
            ),
            ("Boot", format_optional(system.boot_time)),
        ]
    )
    _render_metrics(snapshot.metrics)
    _render_disks(snapshot.disks)


def _render_metrics(metrics: DeviceMetrics) -> None:
    print_heading("Resources")
    print_summary(
        [
            (
                "CPU",
                f"{format_percent(metrics.cpu_percent)}  "
                f"({format_optional(metrics.cpu_count_logical)} cores)",
            ),
            (
                "Memory",
                f"{format_bytes(metrics.memory_used_bytes)} / "
                f"{format_bytes(metrics.memory_total_bytes)}",
            ),
            (
                "Load",
                f"{format_optional(metrics.load_1)} / "
                f"{format_optional(metrics.load_5)} / "
                f"{format_optional(metrics.load_15)}",
            ),
            (
                "Network",
                f"in {format_bytes(metrics.net_rx_bytes)}  "
                f"out {format_bytes(metrics.net_tx_bytes)}",
            ),
        ]
    )


def _render_disks(disks: list[DiskVolume]) -> None:
    print_result_count("disk", len(disks))
    print_table(
        ["MOUNT", "DEVICE", "FS", "USED", "TOTAL"],
        [
            [
                disk.mount_point,
                disk.device,
                format_optional(disk.filesystem),
                format_bytes(disk.used_bytes),
                format_bytes(disk.total_bytes),
            ]
            for disk in disks
        ],
        widths=[22, 18, 8, 10, 10],
    )


COMMAND_SPECS = [
    CliCommandSpec("device", "full device overview", run_device),
    CliCommandSpec("metrics", "cpu, memory, and load", run_metrics),
    CliCommandSpec("disks", "disk usage by mount point", run_disks),
]
