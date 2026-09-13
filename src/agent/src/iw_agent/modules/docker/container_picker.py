"""Full-screen container picker for ``iw containers -i``."""
from __future__ import annotations

from iw_agent.cli.output import format_field, format_optional
from iw_agent.cli.tui.card_picker import LIST_FOOTER, CardItem, PickResult, pick_card
from iw_agent.cli.tui.cards import card_lines
from iw_agent.modules.docker.schemas import Container, PublishedPort

STOPPED_STATES = frozenset({"exited", "stopped", "dead"})


def _format_ports(ports: list[PublishedPort]) -> str:
    if not ports:
        return "—"
    return ", ".join(str(port) for port in ports)


def _container_card(container: Container) -> CardItem[Container]:
    body = [
        format_field("Why", "isolated application box managed by Docker"),
        format_field(
            "Project",
            format_optional(container.compose_project_name, fallback="standalone"),
        ),
        format_field("Image", container.image_name or "—"),
        format_field("Status", container.state),
        format_field("Ports", _format_ports(container.published_ports)),
    ]
    if container.compose_service_name:
        body.insert(3, format_field("Service", container.compose_service_name))
    return CardItem(
        lines=card_lines(
            container.container_name,
            body,
            strike_title=container.state.lower() in STOPPED_STATES,
        ),
        value=container,
    )


def container_cards(containers: list[Container]) -> list[CardItem[Container]]:
    return [_container_card(container) for container in containers]


async def pick_container(
    containers: list[Container],
    *,
    summary: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[Container]:
    return await pick_card(
        container_cards(containers),
        title="Containers",
        subtitle="docker",
        summary=summary,
        footer=LIST_FOOTER,
        dry_run=dry_run,
        terminal=terminal,
    )
