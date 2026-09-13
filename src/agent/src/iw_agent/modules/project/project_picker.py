"""Full-screen project picker for ``iw project -i``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from iw_agent.cli.output import format_field, format_optional
from iw_agent.cli.tui.card_picker import CardItem, PickResult, pick_card
from iw_agent.cli.tui.cards import card_lines
from iw_agent.modules.project.display import project_status_label
from iw_agent.modules.project.schemas import ProjectSummary

FOOTER = "↑↓ select  enter open  q quit"


@dataclass(frozen=True)
class ProjectListChoice:
    kind: Literal["project", "add"]
    project: ProjectSummary | None = None


def _project_card(project: ProjectSummary) -> CardItem[ProjectListChoice]:
    body = [
        format_field("Why", "registered app in your workspace"),
        format_field("Type", project.kind.value),
        format_field("Status", project_status_label(project)),
        format_field("Domain", format_optional(project.domain, fallback="—")),
        format_field("Source", project.source_type),
    ]
    return CardItem(
        lines=card_lines(project.name, body),
        value=ProjectListChoice(kind="project", project=project),
    )


def _add_card() -> CardItem[ProjectListChoice]:
    body = [
        format_field("Why", "register an existing clone or git URL"),
        format_field("Hint", "local path or git URL — does not start the app"),
    ]
    return CardItem(
        lines=card_lines("Register project", body),
        value=ProjectListChoice(kind="add"),
    )


def project_list_cards(
    projects: list[ProjectSummary],
) -> list[CardItem[ProjectListChoice]]:
    return [_project_card(project) for project in projects] + [_add_card()]


async def pick_project(
    projects: list[ProjectSummary],
    *,
    summary: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[ProjectListChoice]:
    return await pick_card(
        project_list_cards(projects),
        title="Projects",
        subtitle="project",
        summary=summary,
        footer=FOOTER,
        dry_run=dry_run,
        terminal=terminal,
    )
