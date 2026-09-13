"""Full-screen process picker for ``iw processes -i``."""
from __future__ import annotations

import psutil

from iw_agent.cli.output import (
    format_field,
    format_memory_meter,
    format_meter,
    format_optional,
)
from iw_agent.cli.tui.card_picker import LIST_FOOTER, CardItem, PickResult, pick_card
from iw_agent.cli.tui.cards import card_lines
from iw_agent.modules.processes.schemas import Process


def _owner_label(process: Process) -> str:
    if process.cgroup_type == "container" and process.container_id:
        return f"docker container {process.container_id}"
    if process.systemd_unit:
        return f"service {process.systemd_unit}"
    if process.owner:
        return f"user {process.owner}"
    return format_optional(process.cgroup_owner, fallback="this server")


def _process_card(
    process: Process,
    rank: int,
    system_ram_total: int,
) -> CardItem[Process]:
    body = [
        format_field("Why", "one of the busiest programs on this server"),
        format_field("Rank", f"#{rank} by CPU"),
        format_field("CPU", format_meter("CPU", process.cpu_percent or 0.0).strip()),
        format_field(
            "Memory",
            format_memory_meter(process.memory_rss_bytes, system_ram_total).strip(),
        ),
        format_field("State", format_optional(process.status, fallback="unknown")),
        format_field("Runs as", _owner_label(process)),
    ]
    if process.command_line:
        command = process.command_line
        if len(command) > 60:
            command = f"{command[:57]}..."
        body.append(format_field("Command", command))
    return CardItem(
        lines=card_lines(f"{process.process_name}  pid {process.pid}", body),
        value=process,
    )


def process_cards(processes: list[Process]) -> list[CardItem[Process]]:
    system_ram_total = psutil.virtual_memory().total
    return [
        _process_card(process, rank, system_ram_total)
        for rank, process in enumerate(processes, start=1)
    ]


async def pick_process(
    processes: list[Process],
    *,
    summary: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[Process]:
    return await pick_card(
        process_cards(processes),
        title="Running programs",
        subtitle="processes",
        summary=summary,
        footer=LIST_FOOTER,
        dry_run=dry_run,
        terminal=terminal,
    )
