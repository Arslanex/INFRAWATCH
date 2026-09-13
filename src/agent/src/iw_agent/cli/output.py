from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from iw_agent.core.schemas import AgentModel

_plain_mode = False
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def configure_output(*, plain: bool = False) -> None:
    global _plain_mode
    _plain_mode = plain or bool(os.environ.get("NO_COLOR"))


def _c(code: str) -> str:
    return "" if _plain_mode else code


def _reset() -> str:
    return "" if _plain_mode else "\033[0m"


BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"

COLUMN_COLORS = (CYAN, YELLOW, GREEN, BLUE, MAGENTA)


def clear_screen() -> None:
    if _plain_mode:
        print()
        return
    print("\033[2J\033[H", end="")


def _visible_length(text: str) -> int:
    return len(_ANSI_RE.sub("", text))


def _pad_visible(text: str, width: int) -> str:
    padding = width - _visible_length(text)
    if padding <= 0:
        return text
    return text + (" " * padding)


def _color_cell(text: str, color: str) -> str:
    if _plain_mode or _ANSI_RE.search(text):
        return text
    return f"{_c(color)}{text}{_reset()}"


def print_banner() -> None:
    print()
    print(f"{_c(BOLD)}{_c(CYAN)}InfraWatch{_reset()} {_c(DIM)}— server inspection tool{_reset()}")
    print(f"{_c(DIM)}Pick a command, e.g.  iw device  ·  iw ports  ·  iw containers{_reset()}")
    print()


def print_report(title: str, subtitle: str) -> None:
    line = "═" * 52
    print()
    print(f"{_c(CYAN)}{line}{_reset()}")
    print(f"{_c(BOLD)}  {title}{_reset()}")
    print(f"{_c(DIM)}  {subtitle}{_reset()}")
    print(f"{_c(CYAN)}{line}{_reset()}")
    print()


def print_insight(text: str) -> None:
    print(f"{_c(BOLD)}{_c(BLUE)}Summary{_reset()}  {text}")
    print()


def print_section(step: int, title: str, description: str) -> None:
    marker = f"{step}." if step > 0 else "•"
    print(f"{_c(BOLD)}{marker} {title}{_reset()}")
    print(f"   {_c(DIM)}{description}{_reset()}")
    print()


def print_labeled_rows(rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(
            f"   {_c(BOLD)}{_c(CYAN)}{label:<{width}}{_reset()}  {value}"
        )
    print()


def print_empty(title: str, reason: str, hint: str) -> None:
    print(f"   {_c(YELLOW)}Nothing to show — {title}{_reset()}")
    print(f"   {_c(DIM)}{reason}{_reset()}")
    print(f"   {_c(DIM)}Tip: {hint}{_reset()}")
    print()


def print_data_table(
    columns: list[tuple[str, str]],
    rows: list[list[str]],
) -> None:
    headers = [header for header, _ in columns]
    if not rows:
        print(f"   {_c(DIM)}(no rows){_reset()}\n")
        return

    widths = [
        max(
            len(headers[index]),
            *(_visible_length(row[index]) for row in rows),
        )
        for index in range(len(headers))
    ]
    separator = f"{_c(DIM)} │ {_reset()}"

    header_parts = []
    for index, header in enumerate(headers):
        color = COLUMN_COLORS[index % len(COLUMN_COLORS)]
        header_parts.append(
            _pad_visible(
                f"{_c(BOLD)}{_c(color)}{header}{_reset()}",
                widths[index],
            )
        )
    print("   " + separator.join(header_parts))

    for row in rows:
        row_parts = []
        for index, cell in enumerate(row):
            color = COLUMN_COLORS[index % len(COLUMN_COLORS)]
            row_parts.append(_pad_visible(_color_cell(cell, color), widths[index]))
        print("   " + separator.join(row_parts))
    print()


def print_column_guide(columns: list[tuple[str, str]]) -> None:
    print(f"   {_c(DIM)}What the columns mean:{_reset()}")
    for index, (header, explanation) in enumerate(columns):
        color = COLUMN_COLORS[index % len(COLUMN_COLORS)]
        print(
            f"   {_c(color)}  • {header}:{_reset()} {_c(DIM)}{explanation}{_reset()}"
        )
    print()


def print_note(text: str) -> None:
    print(f"{_c(DIM)}Note: {text}{_reset()}")
    print()


def format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value < 1024:
        return f"{value} bytes"
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KB"
    if value < 1024 ** 3:
        return f"{value / (1024 ** 2):.1f} MB"
    return f"{value / (1024 ** 3):.1f} GB"


def format_percent(value: float | None, *, colorize: bool = False) -> str:
    if value is None:
        return "unknown"
    text = f"{value:.1f}%"
    if not colorize:
        return text
    if value >= 85:
        color = RED
    elif value >= 50:
        color = YELLOW
    else:
        color = GREEN
    return f"{_c(color)}{text}{_reset()}"


def format_disk_status(used_bytes: int, total_bytes: int) -> str:
    if total_bytes <= 0:
        return "unknown"
    percent = (used_bytes / total_bytes) * 100
    if percent >= 90:
        return f"{_c(RED)}critically full{_reset()}"
    if percent >= 75:
        return f"{_c(YELLOW)}getting full{_reset()}"
    return f"{_c(GREEN)}ok{_reset()}"


def format_optional(value: Any, *, fallback: str = "unknown") -> str:
    if value is None:
        return fallback
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


def format_usage_ratio(used: int | None, total: int | None) -> str:
    if used is None or total is None or total <= 0:
        return "unknown"
    percent = (used / total) * 100
    text = f"{format_bytes(used)} of {format_bytes(total)} ({percent:.0f}% full)"
    if percent >= 90:
        return f"{_c(RED)}{text}{_reset()}"
    if percent >= 75:
        return f"{_c(YELLOW)}{text}{_reset()}"
    return f"{_c(GREEN)}{text}{_reset()}"


def format_cpu_line(percent: float | None, cores: int | None) -> str:
    if percent is None:
        return "unknown"
    core_text = f"{cores} cores" if cores is not None else "cores unknown"
    if percent >= 85:
        color = RED
    elif percent >= 60:
        color = YELLOW
    else:
        color = GREEN
    return f"{_c(color)}{format_percent(percent)}{_reset()} across {core_text}"


def format_load_line(load_1: float | None, load_5: float | None, load_15: float | None) -> str:
    if load_1 is None:
        return "unknown"
    load_5_text = f"{load_5:.2f}" if load_5 is not None else "?"
    load_15_text = f"{load_15:.2f}" if load_15 is not None else "?"
    return (
        f"now {load_1:.2f}, last 5 min {load_5_text}, last 15 min {load_15_text} "
        f"{_c(DIM)}(higher = busier){_reset()}"
    )


def format_state(state: str) -> str:
    lowered = state.lower()
    if lowered == "running":
        return f"{_c(GREEN)}{state}{_reset()}"
    if lowered in {"exited", "stopped", "dead"}:
        return f"{_c(DIM)}{state}{_reset()}"
    return f"{_c(YELLOW)}{state}{_reset()}"


def format_exit_code(code: int) -> str:
    if code == 0:
        return f"{_c(GREEN)}OK (0){_reset()}"
    return f"{_c(RED)}failed ({code}){_reset()}"


def format_ssl_enabled(enabled: bool) -> str:
    if enabled:
        return f"{_c(GREEN)}HTTPS yes{_reset()}"
    return f"{_c(DIM)}HTTPS no{_reset()}"


def emit_json(payload: Any, *, stream: Any = None) -> None:
    target = stream or sys.stdout

    if isinstance(payload, AgentModel):
        data = payload.model_dump(mode="json")
    elif isinstance(payload, list) and payload and isinstance(payload[0], AgentModel):
        data = [item.model_dump(mode="json") for item in payload]
    else:
        data = payload

    json.dump(data, target, indent=2, default=str, ensure_ascii=False)
    print(file=target)


def emit_models(
    payload: AgentModel | Sequence[AgentModel],
    *,
    json_output: bool,
    plain: bool = False,
    render: Callable[[Any], None],
) -> None:
    configure_output(plain=plain)
    if json_output:
        emit_json(payload)
        return
    clear_screen()
    render(payload)
