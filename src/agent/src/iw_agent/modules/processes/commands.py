from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_bytes,
    format_optional,
    format_percent,
    print_column_guide,
    print_data_table,
    print_empty,
    print_insight,
    print_report,
    print_section,
)
from iw_agent.cli.parser import add_limit_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.processes.collector import collect_processes
from iw_agent.modules.processes.schemas import Process

PROCESS_COLUMNS = [
    ("Program", "name of the running software"),
    ("CPU", "processor usage right now"),
    ("Memory", "RAM used by the program"),
    ("Runs as", "container, service, or other owner"),
]


async def run_processes(args: argparse.Namespace) -> None:
    processes = await collect_processes(args.limit)
    emit_models(processes, json_output=args.json, plain=args.plain, render=_render_processes)


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

    top = processes[0]
    print_insight(
        f"The busiest program right now is {top.process_name} "
        f"using {format_percent(top.cpu_percent)} CPU."
    )

    print_section(1, "Top programs", "Highest CPU usage at this moment.")
    print_data_table(
        PROCESS_COLUMNS,
        [
            [
                process.process_name,
                format_percent(process.cpu_percent, colorize=True),
                format_bytes(process.memory_rss_bytes),
                _owner_label(process),
            ]
            for process in processes
        ],
    )
    print_column_guide(PROCESS_COLUMNS)


def _owner_label(process: Process) -> str:
    if process.cgroup_type == "container" and process.container_id:
        return f"docker container {process.container_id}"
    if process.systemd_unit:
        return f"service {process.systemd_unit}"
    return format_optional(process.cgroup_owner, fallback="this server")


def _configure(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=10, help_text="max processes")


COMMAND_SPECS = [
    CliCommandSpec("processes", "top processes by cpu", run_processes, _configure),
]
