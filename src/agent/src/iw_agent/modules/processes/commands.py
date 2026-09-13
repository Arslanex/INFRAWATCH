from __future__ import annotations

import argparse

import psutil

from iw_agent.cli.output import (
    BLUE,
    DIM,
    GREEN,
    RED,
    YELLOW,
    _c,
    _reset,
    emit_models,
    format_field,
    format_fields,
    format_memory_meter,
    format_meter,
    format_optional,
    format_percent,
    print_empty,
    print_info_box,
    print_insight,
    print_report,
    print_status_box,
    process_load_details,
    status_badge,
)
from iw_agent.cli.parser import add_limit_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.processes.collector import collect_processes
from iw_agent.modules.processes.schemas import Process


async def run_processes(args: argparse.Namespace) -> None:
    processes = await collect_processes(args.limit)
    emit_models(processes, json_output=args.json, plain=args.plain, render=_render_processes)


def _processes_summary(processes: list[Process]) -> str:
    top = processes[0]
    total_cpu = sum(process.cpu_percent or 0.0 for process in processes)
    return (
        f"Top {len(processes)} programs use {total_cpu:.1f}% CPU combined. "
        f"Busiest: {top.process_name} ({format_percent(top.cpu_percent)})."
    )


def _owner_label(process: Process) -> str:
    if process.cgroup_type == "container" and process.container_id:
        return f"docker container {process.container_id}"
    if process.systemd_unit:
        return f"service {process.systemd_unit}"
    if process.owner:
        return f"user {process.owner}"
    return format_optional(process.cgroup_owner, fallback="this server")


def _status_legend() -> str:
    parts = [
        status_badge("IDLE", "ok"),
        status_badge("WORKING", "work"),
        status_badge("WAITING", "work"),
        status_badge("HOT", "warn"),
        status_badge("BUSY", "bad"),
        status_badge("STOPPED", "off"),
        status_badge("ZOMBIE", "bad"),
    ]
    return " · ".join(parts)


def _render_process_card(process: Process, rank: int, system_ram_total: int) -> None:
    load_badge, tone = process_load_details(
        process.cpu_percent,
        process_status=process.status,
    )
    badge = f"#{rank} {load_badge}"

    lines = [
        format_meter("CPU", process.cpu_percent or 0.0),
        format_memory_meter(process.memory_rss_bytes, system_ram_total),
        format_field("State", format_optional(process.status, fallback="unknown")),
        format_field("Runs as", _owner_label(process)),
        format_field("PID", str(process.pid)),
    ]

    if process.command_line:
        command = process.command_line
        if len(command) > 72:
            command = f"{command[:69]}..."
        lines.append(format_field("Command", command))

    print_status_box(
        badge=badge,
        title=process.process_name,
        lines=lines,
        tone=tone,
    )


def _render_processes(processes: list[Process]) -> None:
    print_report(
        "Running programs",
        "The busiest programs on this server, sorted by CPU usage.",
    )
    if not processes:
        print_empty(
            "no processes listed",
            "The agent could not read the process list.",
            "try: sudo iw processes",
        )
        return

    print_insight(_processes_summary(processes))
    print_info_box(
        title="How to read",
        hint="status colors",
        lines=format_fields(
            [
                ("CPU / RAM", "bars show real usage on this server"),
                ("State", "raw psutil status (running, sleeping, zombie, …)"),
                (
                    "Colors",
                    f"{_c(GREEN)}idle{_reset()} · {_c(BLUE)}working/waiting{_reset()} · "
                    f"{_c(YELLOW)}hot{_reset()} · {_c(RED)}busy/dead{_reset()} · "
                    f"{_c(DIM)}stopped{_reset()}",
                ),
            ]
        )
        + [_status_legend()],
    )

    system_ram_total = psutil.virtual_memory().total
    for rank, process in enumerate(processes, start=1):
        _render_process_card(process, rank, system_ram_total)


def _configure(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=10, help_text="max processes")


COMMAND_SPECS = [
    CliCommandSpec("processes", "top processes by cpu", run_processes, _configure),
]
