from __future__ import annotations

from typing import Sequence

from iw_agent.cli.interactive.selector import prompt_choice
from iw_agent.cli.output import DIM, _c, _reset, print_page_divider
from iw_agent.core.actions import ActionKind, ActionSpec


_KIND_LABELS = {
    ActionKind.READ: ("read", "ok"),
    ActionKind.WRITE: ("write", "work"),
    ActionKind.DESTRUCTIVE: ("destructive", "bad"),
}


def print_action_menu(actions: Sequence[ActionSpec]) -> None:
    print_page_divider()
    print(f"{_c(DIM)}Actions{_reset()}\n")
    for index, action in enumerate(actions, start=1):
        tag, tone = _KIND_LABELS[action.kind]
        color = {"ok": "\033[32m", "work": "\033[34m", "bad": "\033[31m"}[tone]
        root = " root" if action.requires_root else ""
        print(
            f"  {index:2}. {_c(color)}{action.label}{_reset()}"
            f"  {_c(DIM)}[{tag}{root}]{_reset()}",
        )
        if action.description:
            print(f"      {_c(DIM)}{action.description}{_reset()}")


def select_action(actions: Sequence[ActionSpec]) -> ActionSpec | None:
    if not actions:
        return None
    choice = prompt_choice(max_value=len(actions), allow_back=True, allow_exit=True)
    if choice is None:
        return None
    if choice == -1:
        return None
    return actions[choice - 1]
