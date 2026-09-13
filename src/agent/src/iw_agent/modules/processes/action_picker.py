"""Action picker for a selected process."""
from __future__ import annotations

from iw_agent.cli.tui.card_picker import PickResult
from iw_agent.cli.interactive.hub import HubAction, pick_hub_action
from iw_agent.modules.processes.schemas import Process


def hub_actions(process: Process) -> list[HubAction]:
    return [
        HubAction("View details", "CPU, memory, cgroup, command", "view_details"),
        HubAction("Kill process", "send SIGTERM (type YES to confirm)", "kill_process"),
    ]


async def pick_process_action(
    process: Process,
    *,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[HubAction]:
    return await pick_hub_action(
        hub_actions(process),
        title=f"{process.process_name} (pid {process.pid})",
        subtitle="processes · actions",
        dry_run=dry_run,
        terminal=terminal,
    )
