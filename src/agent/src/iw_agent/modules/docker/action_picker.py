"""Action picker for a selected Docker container."""
from __future__ import annotations

from iw_agent.cli.tui.card_picker import PickResult
from iw_agent.cli.interactive.hub import HubAction, pick_hub_action
from iw_agent.modules.docker.schemas import Container

_LOGS = HubAction("Logs", "last stdout/stderr lines", "view_logs")
_DETAILS = HubAction("View details", "image, ports, compose", "view_details")


def hub_actions(container: Container) -> list[HubAction]:
    if container.state.lower() == "running":
        return [
            HubAction("Restart", "stop then start", "restart_container"),
            HubAction("Stop", "graceful shutdown", "stop_container"),
            _LOGS,
            _DETAILS,
        ]
    return [
        HubAction("Start", "bring container up", "start_container"),
        _LOGS,
        _DETAILS,
    ]


async def pick_container_action(
    container: Container,
    *,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[HubAction]:
    return await pick_hub_action(
        hub_actions(container),
        title=container.container_name,
        subtitle="docker · actions",
        dry_run=dry_run,
        terminal=terminal,
    )
