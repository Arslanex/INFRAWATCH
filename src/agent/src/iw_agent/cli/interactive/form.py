"""Styled prompts for multi-step CLI wizards — retry on bad input, quit with q."""
from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Optional

from iw_agent.cli.output import DIM, YELLOW, _c, _reset, print_group_heading, print_page_summary

Validator = Callable[[str], Optional[str]]


def print_form_warning(message: str) -> None:
    print(f"   {_c(YELLOW)}! {message}{_reset()}")


def print_form_step(*, step: int, total: int, title: str, hint: str | None = None) -> None:
    print()
    print_page_summary(f"Step {step} of {total}")
    print_group_heading(title, hint)


def prompt_text(
    label: str,
    *,
    hint: str = "",
    default: str = "",
    allow_empty: bool = False,
    allow_exit: bool = True,
    validator: Validator | None = None,
) -> str | None:
    """Read a line; return ``None`` when the user quits."""
    if hint:
        print(f"   {_c(DIM)}{hint}{_reset()}")
    while True:
        suffix = f"  {_c(DIM)}[{default}]{_reset()}" if default else ""
        raw = input(f"   {label}{suffix}\n   > ").strip()
        if allow_exit and raw.lower() in {"q", "quit", "exit"}:
            return None
        if not raw and default:
            raw = default
        if not raw and not allow_empty:
            print_form_warning("This field is required — try again or q to cancel.")
            continue
        if validator:
            error = validator(raw)
            if error:
                print_form_warning(error)
                continue
        return raw


def prompt_int(
    label: str,
    *,
    hint: str = "",
    minimum: int = 1,
    maximum: int = 65535,
    allow_exit: bool = True,
) -> int | None:
    def _validate(raw: str) -> str | None:
        try:
            value = int(raw)
        except ValueError:
            return "Enter a whole number."
        if value < minimum or value > maximum:
            return f"Enter a number between {minimum} and {maximum}."
        return None

    text = prompt_text(
        label,
        hint=hint,
        allow_empty=False,
        allow_exit=allow_exit,
        validator=_validate,
    )
    if text is None:
        return None
    return int(text)


def prompt_choice_menu(
    *,
    step: int,
    total: int,
    title: str,
    hint: str | None,
    options: list[tuple[str, str | None]],
    allow_back: bool = False,
    allow_exit: bool = True,
) -> int | None:
    """Show a numbered menu; return 1-based choice, ``-1`` back, ``None`` quit."""
    from iw_agent.cli.interactive.selector import prompt_choice
    from iw_agent.cli.output import print_menu_item, print_nav_hint

    print_form_step(step=step, total=total, title=title, hint=hint)
    for index, (label, option_hint) in enumerate(options, start=1):
        print_menu_item(index, label, option_hint)
    print_nav_hint(allow_back=allow_back)
    return prompt_choice(max_value=len(options), allow_back=allow_back, allow_exit=allow_exit)
