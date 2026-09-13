from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_bytes,
    format_optional,
    format_percent,
    print_result_count,
    print_table,
)
from iw_agent.cli.parser import add_limit_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.processes.collector import collect_processes
from iw_agent.modules.processes.schemas import Process


async def run_processes(args: argparse.Namespace) -> None:
    processes = await collect_processes(args.limit)
    emit_models(processes, json_output=args.json, render=_render_processes)


def _render_processes(processes: list[Process]) -> None:
    print_result_count("process", len(processes))
    print_table(
        ["PID", "CPU", "MEMORY", "NAME", "OWNER", "CGROUP"],
        [
            [
                str(process.pid),
                format_percent(process.cpu_percent),
                format_bytes(process.memory_rss_bytes),
                process.process_name,
                format_optional(process.cgroup_owner),
                format_optional(process.cgroup_type),
            ]
            for process in processes
        ],
        widths=[8, 8, 10, 16, 20, 12],
    )


def _configure(parser: argparse.ArgumentParser) -> None:
    add_limit_flag(parser, default=10, help_text="max processes")


COMMAND_SPECS = [
    CliCommandSpec("processes", "top processes by cpu", run_processes, _configure),
]
