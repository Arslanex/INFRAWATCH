"""Action picker for a selected project."""
from __future__ import annotations

from iw_agent.cli.tui.card_picker import PickResult
from iw_agent.cli.interactive.hub import HubAction, pick_hub_action
from iw_agent.modules.project.display import primary_action_hint, primary_action_label
from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary


def hub_actions(project: ProjectSummary) -> list[HubAction]:
    actions = [
        HubAction(
            primary_action_label(project.kind),
            primary_action_hint(project.kind),
            "deploy",
        ),
        HubAction("Edit nginx", "open site config in the structural editor", "nginx"),
    ]
    if project.kind is ProjectKind.DOCKER_COMPOSE:
        actions.append(HubAction("Stop stack", "docker compose down", "stop"))
    actions.append(HubAction("Details", "repo path and manifest", "more"))
    actions.append(
        HubAction(
            "Re-detect stack",
            "refresh type and port checks after repo changes",
            "detect",
        ),
    )
    return actions


async def pick_project_action(
    project: ProjectSummary,
    *,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[HubAction]:
    return await pick_hub_action(
        hub_actions(project),
        title=project.name,
        subtitle="project · actions",
        dry_run=dry_run,
        terminal=terminal,
    )
