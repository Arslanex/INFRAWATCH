"""Compact card bodies shared by every module's picker."""
from __future__ import annotations

from iw_agent.cli.output import BOLD, DIM, _c, _reset, format_strikethrough


def card_lines(title: str, body: list[str], *, strike_title: bool = False) -> list[str]:
    """One compact card: a bold (or struck-through) title over ``Label: value`` rows."""
    bar = f"{_c(DIM)}│{_reset()}"
    display_title = format_strikethrough(title) if strike_title else f"{_c(BOLD)}{title}{_reset()}"
    return [f" {bar} {display_title}"] + [f" {bar} {line}" for line in body]
