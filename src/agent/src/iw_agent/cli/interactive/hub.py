"""The loop every module's interactive session runs: pick a target, act on it."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Optional, TypeVar

from iw_agent.cli.interactive.selector import prompt_choice
from iw_agent.cli.output import (
    clear_screen,
    format_field,
    print_menu_item,
    print_nav_hint,
    print_page_header,
)
from iw_agent.cli.tui.card_picker import (
    BACK_KEYS,
    HUB_FOOTER,
    CardItem,
    CardPickerUnavailable,
    PickResult,
    pick_card,
)
from iw_agent.cli.tui.cards import card_lines

T = TypeVar("T")


@dataclass(frozen=True)
class HubAction:
    """One entry in a target's action hub."""

    label: str
    hint: str
    action_id: str = ""
    kind: Literal["executor", "local"] = "executor"


async def pick_or_fallback(
    pick: Callable[[], Awaitable[PickResult[T]]],
    fallback: Callable[[], Awaitable[Optional[T]]],
) -> PickResult[T]:
    """Run the full-screen picker, or a numbered menu where it cannot be drawn.

    The fallback returns ``None`` when the user quits, since a numbered menu
    has no separate "back" out of the top level.
    """
    try:
        return await pick()
    except CardPickerUnavailable:
        value = await fallback()
        return PickResult(value=value, quit_session=value is None)


async def pick_hub_action(
    actions: list[HubAction],
    *,
    title: str,
    subtitle: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[HubAction]:
    items = [
        CardItem(lines=card_lines(action.label, [format_field("Hint", action.hint)]), value=action)
        for action in actions
    ]
    try:
        return await pick_card(
            items,
            title=title,
            subtitle=subtitle,
            footer=HUB_FOOTER,
            dry_run=dry_run,
            back_keys=BACK_KEYS,
            terminal=terminal,
        )
    except CardPickerUnavailable:
        return _hub_action_fallback(actions, title=title, subtitle=subtitle)


def _hub_action_fallback(
    actions: list[HubAction],
    *,
    title: str,
    subtitle: str,
) -> PickResult[HubAction]:
    """Numbered menu for terminals the full-screen hub cannot be drawn in."""
    if not actions:
        return PickResult()

    clear_screen()
    print_page_header(title, subtitle)
    for index, action in enumerate(actions, start=1):
        print_menu_item(index, action.label, action.hint)
    print_nav_hint(allow_back=True)

    choice = prompt_choice(max_value=len(actions), allow_back=True, allow_exit=True)
    if choice is None:
        return PickResult(quit_session=True)
    if choice == -1:
        return PickResult()
    return PickResult(value=actions[choice - 1])


async def run_action_hub(
    target: T,
    *,
    pick: Callable[[T], Awaitable[PickResult[HubAction]]],
    perform: Callable[[T, HubAction], Awaitable[Optional[T]]],
) -> bool:
    """Offer a target's actions until the user leaves it.

    ``perform`` returns the target to keep managing — refreshed if the action
    changed it — or ``None`` to drop back to the list. Returns ``True`` when
    the user asked to quit the whole session.
    """
    while True:
        picked = await pick(target)
        if picked.quit_session:
            return True
        if picked.back:
            return False
        updated = await perform(target, picked.value)
        if updated is None:
            return False
        target = updated
