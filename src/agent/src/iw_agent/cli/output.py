from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from iw_agent.core.schemas import AgentModel

_plain_mode = False
_page_divider_printed = False
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


def configure_output(*, plain: bool = False) -> None:
    global _plain_mode, _page_divider_printed
    _plain_mode = plain or bool(os.environ.get("NO_COLOR"))
    _page_divider_printed = False


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
STRIKE = "\033[9m"
BG_SELECTED = "\033[48;5;24m"
BG_EDITING = "\033[48;5;28m"

COLUMN_COLORS = (CYAN, YELLOW, GREEN, BLUE, MAGENTA)
INFO_BOX_COLOR = MAGENTA
_PAGE_WIDTH = 52
_PAGE_ACCENT = BLUE
_BOX_WIDTH = 44
_TONE_BORDERS = {
    "ok": GREEN,
    "work": BLUE,
    "warn": YELLOW,
    "bad": RED,
    "off": DIM,
    "info": INFO_BOX_COLOR,
}


def clear_screen() -> None:
    if _plain_mode:
        print()
        return
    if sys.stdout.isatty():
        print("\033[2J\033[H", end="", flush=True)
        return
    print()


def prepare_command_view(*, plain: bool = False) -> None:
    configure_output(plain=plain)
    clear_screen()


def visible_length(text: str) -> int:
    """Width of ``text`` on screen, ignoring ANSI colour codes."""
    return len(_ANSI_RE.sub("", text))


def pad_visible(text: str, width: int) -> str:
    padding = width - visible_length(text)
    if padding <= 0:
        return text
    return text + (" " * padding)


def highlight_row(
    text: str,
    *,
    selected: bool = False,
    editing: bool = False,
    width: int | None = None,
) -> str:
    """Paint a TUI row — ``editing`` wins over ``selected`` (full width if given)."""
    if width is not None:
        text = pad_visible(text, width)
    if _plain_mode or (not selected and not editing):
        return text
    bg = BG_EDITING if editing else BG_SELECTED
    return f"{_c(bg)}{text}{_reset()}"


def truncate_visible(text: str, width: int, *, ellipsis: str = "\u2026") -> str:
    """Cut ``text`` to ``width`` columns, keeping colour codes balanced."""
    if width <= 0:
        return ""
    if visible_length(text) <= width:
        return text

    keep = width - len(ellipsis)
    out = []
    seen = 0
    index = 0
    while index < len(text) and seen < keep:
        match = _ANSI_RE.match(text, index)
        if match:
            out.append(match.group())
            index = match.end()
            continue
        out.append(text[index])
        seen += 1
        index += 1
    out.append(ellipsis)
    if _ANSI_RE.search(text):
        out.append(_reset())
    return "".join(out)


# the underscore spellings predate the TUI; kept so existing callers work
_visible_length = visible_length
_pad_visible = pad_visible


def _color_cell(text: str, color: str) -> str:
    if _plain_mode or _ANSI_RE.search(text):
        return text
    return f"{_c(color)}{text}{_reset()}"


def print_page_divider() -> None:
    global _page_divider_printed
    print(f"   {_c(DIM)}{'─' * _PAGE_WIDTH}{_reset()}")
    _page_divider_printed = True


def print_page_header(title: str, subtitle: str) -> None:
    print()
    if subtitle:
        print(
            f"   {_c(DIM)}{subtitle}{_reset()}",
        )
        print(f"   {_c(BOLD)}{title}{_reset()}")
        return
    print(f"   {_c(BOLD)}{title}{_reset()}")


def print_page_summary(text: str) -> None:
    print(f"   {_c(DIM)}{text}{_reset()}")


def print_menu_item(index: int | str, label: str, hint: str | None = None) -> None:
    marker = f"{index:>2}." if isinstance(index, int) else f" {index} "
    if hint:
        print(f"  {marker} {label}  {_c(DIM)}{hint}{_reset()}")
        return
    print(f"  {marker} {label}")


def print_menu_list(items: list[tuple[int | str, str, str | None]]) -> None:
    for entry in items:
        if len(entry) == 2:
            print_menu_item(entry[0], entry[1])
        else:
            print_menu_item(entry[0], entry[1], entry[2])


def print_nav_hint(*, allow_back: bool) -> None:
    parts = ["b back"] if allow_back else []
    parts.append("q quit")
    print(f"\n   {_c(DIM)}{' · '.join(parts)}{_reset()}")


def print_banner() -> None:
    print()
    print(
        f"   {_c(BOLD)}{_c(_PAGE_ACCENT)}InfraWatch{_reset()}"
        f"  {_c(DIM)}server inspection tool{_reset()}"
    )
    print(f"   {_c(DIM)}iw device · iw ports · iw containers{_reset()}")
    print_page_divider()


def print_report(title: str, subtitle: str) -> None:
    print_page_header(title, subtitle)


def print_insight(text: str) -> None:
    print_page_summary(text)
    print_page_divider()


def print_section(step: int, title: str, description: str) -> None:
    del step
    print_group_heading(title, description)


def print_spacer() -> None:
    print()


def format_label(label: str) -> str:
    if _plain_mode:
        return f"{label}:"
    return f"{_c(BOLD)}{label}:{_reset()}"


def format_field(label: str, value: str, *, label_width: int = 10) -> str:
    gap = max(1, label_width - len(label))
    return f"{format_label(label)}{' ' * gap}{value}"


def format_fields(
    rows: list[tuple[str, str]],
    *,
    label_width: int = 10,
) -> list[str]:
    return [format_field(label, value, label_width=label_width) for label, value in rows]


def status_badge(text: str, tone: str) -> str:
    color = _TONE_BORDERS.get(tone, GREEN)
    bullet = "○" if tone == "off" else "●"
    if _plain_mode:
        return f"[{text}]"
    return f"{_c(color)}{bullet} {text}{_reset()}"


def _print_box_top(border: str, header: str) -> None:
    print(f"   {_c(border)}┌─ {header}{_reset()}")


def _print_box_line(border: str, line: str) -> None:
    print(f"   {_c(border)}│{_reset()} {line}")


def _print_box_bottom(border: str) -> None:
    print(f"   {_c(border)}└{'─' * _BOX_WIDTH}{_reset()}")


def print_info_box(
    *,
    title: str,
    lines: list[str],
    hint: str | None = None,
) -> None:
    header = format_label(title)
    if hint:
        header = f"{header} {_c(DIM)}{hint}{_reset()}"
    _print_box_top(INFO_BOX_COLOR, header)
    for line in lines:
        _print_box_line(INFO_BOX_COLOR, line)
    _print_box_bottom(INFO_BOX_COLOR)


def render_status_box_lines(
    *,
    badge: str,
    title: str,
    lines: list[str],
    tone: str = "ok",
    strike_title: bool = False,
    selected: bool = False,
    prefix: str = " ",
) -> list[str]:
    """Return status-box lines for TUI renderers (same look as :func:`print_status_box`)."""
    border = _TONE_BORDERS.get(tone, GREEN)
    if selected and not _plain_mode:
        border = CYAN
    marker = "▸ " if selected else "  "
    display_title = format_strikethrough(title) if strike_title else f"{_c(BOLD)}{title}{_reset()}"
    body = [
        f"{prefix}{marker}{_c(border)}┌─ {badge}{_reset()}",
        f"{prefix}  {_c(border)}│{_reset()} {display_title}",
    ]
    for line in lines:
        body.append(f"{prefix}  {_c(border)}│{_reset()} {line}")
    body.append(f"{prefix}  {_c(border)}└{'─' * _BOX_WIDTH}{_reset()}")
    return body


def print_status_box(
    *,
    badge: str,
    title: str,
    lines: list[str],
    tone: str = "ok",
    strike_title: bool = False,
) -> None:
    for line in render_status_box_lines(
        badge=badge,
        title=title,
        lines=lines,
        tone=tone,
        strike_title=strike_title,
        prefix="   ",
    ):
        print(line)


def print_group_heading(title: str, hint: str | None = None) -> None:
    if hint:
        print(
            f"   {_c(DIM)}──{_reset()} {_c(BOLD)}{title}{_reset()}"
            f" {_c(DIM)}· {hint}{_reset()}"
        )
    else:
        print(f"   {_c(DIM)}──{_reset()} {_c(BOLD)}{title}{_reset()}")


def print_panel(title: str, *, hint: str | None = None) -> None:
    print_group_heading(title, hint)


def print_labeled_rows(rows: list[tuple[str, str]]) -> None:
    if not rows:
        return
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(
            f"   {_c(BOLD)}{_c(CYAN)}{label:<{width}}{_reset()}  {value}"
        )
    print()


def print_field_rows(
    rows: list[tuple[str, str]],
    *,
    label_width: int = 12,
) -> None:
    for label, value in rows:
        print(f"   {_c(DIM)}{label:<{label_width}}{_reset()} {value}")


def print_labeled_block(label: str, lines: list[str], *, label_width: int | None = None) -> None:
    if not lines:
        return
    width = label_width if label_width is not None else len(label)
    for index, line in enumerate(lines):
        if index == 0:
            print(f"   {_c(BOLD)}{_c(CYAN)}{label:<{width}}{_reset()}  {line}")
        else:
            print(f"   {' ' * width}  {line}")
    print()


def print_empty(title: str, reason: str, hint: str) -> None:
    if not _page_divider_printed:
        print_page_divider()
    print_status_box(
        badge=status_badge("EMPTY", "warn"),
        title=title,
        lines=[
            format_field("Reason", reason, label_width=8),
            format_field("Tip", hint, label_width=8),
        ],
        tone="warn",
    )


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


def _usage_color(percent: float) -> str:
    if percent >= 85:
        return RED
    if percent >= 60:
        return YELLOW
    return GREEN


def _bar_chars() -> tuple[str, str, str]:
    if _plain_mode:
        return "#", ":", "-"
    return "█", "▄", "░"


def format_horizontal_bar(
    percent: float,
    *,
    width: int = 28,
    severity: bool = True,
) -> str:
    clamped = min(100.0, max(0.0, percent))
    exact_fill = (clamped / 100.0) * width
    full_count = int(exact_fill)
    has_half = (exact_fill - full_count) >= 0.5 and full_count < width
    empty_count = width - full_count - (1 if has_half else 0)

    full, partial, empty = _bar_chars()
    color = _usage_color(clamped) if severity else MAGENTA
    bar = f"{_c(color)}{full * full_count}{_reset()}"
    if has_half:
        bar += f"{_c(color)}{partial}{_reset()}"
    bar += f"{_c(DIM)}{empty * empty_count}{_reset()}"
    return bar


def format_cpu_line(percent: float | None, cores: int | None) -> str:
    if percent is None:
        return "unknown"
    core_text = f"{cores} cores" if cores is not None else "cores unknown"
    color = _usage_color(percent)
    return f"{_c(color)}{format_percent(percent)}{_reset()} across {core_text}"


def format_usage_meter(
    label: str,
    percent: float,
    detail: str = "",
    *,
    width: int = 22,
    label_width: int = 8,
) -> str:
    line = format_meter(label, percent, width=width, label_width=label_width)
    if detail:
        return f"{line}  {_c(DIM)}{detail}{_reset()}"
    return line


def format_usage_row(
    label: str,
    percent: float,
    detail: str,
    *,
    width: int = 22,
    label_width: int = 10,
) -> str:
    return f"   {format_usage_meter(label, percent, detail, width=width)}"


def format_cpu_core_meters(
    percents: list[float],
    *,
    width: int = 22,
) -> list[str]:
    if not percents:
        return ["unknown"]

    average = sum(percents) / len(percents)
    lines = [
        format_usage_meter(
            "Overall",
            average,
            f"{len(percents)} cores",
            width=width,
        )
    ]
    for index, percent in enumerate(percents):
        lines.append(format_usage_meter(f"Core {index}", percent, width=width))
    return lines


def format_memory_meter_line(
    used: int | None,
    total: int | None,
    *,
    width: int = 22,
) -> str:
    if used is None or total is None or total <= 0:
        return f"{format_label('RAM')}     [----------------------] unknown"
    return format_memory_meter(used, total, width=width)


def format_load_meter_line(
    load_1: float | None,
    load_5: float | None,
    load_15: float | None,
    cores: int | None,
    *,
    width: int = 22,
) -> str:
    if load_1 is None:
        return f"{format_label('Load')}    [----------------------] unknown"

    load_5_text = f"{load_5:.2f}" if load_5 is not None else "?"
    load_15_text = f"{load_15:.2f}" if load_15 is not None else "?"
    detail = f"now {load_1:.2f} · 5m {load_5_text} · 15m {load_15_text}"
    percent = min(100.0, (load_1 / cores) * 100) if cores and cores > 0 else min(100.0, load_1 * 100)
    return format_usage_meter("Load", percent, detail, width=width)


def format_disk_meters(
    partitions: list[tuple[str, int, int]],
    *,
    width: int = 22,
    label_width: int = 10,
) -> list[str]:
    if not partitions:
        return ["unknown"]

    lines: list[str] = []
    for mount, used, total in partitions:
        if total <= 0:
            continue
        percent = (used / total) * 100
        label = mount if len(mount) <= label_width else mount[: label_width - 1] + "…"
        lines.append(
            format_usage_meter(
                label,
                percent,
                f"{format_bytes(used)} / {format_bytes(total)}",
                width=width,
            )
        )
    return lines or ["unknown"]


def print_usage_lines(lines: list[str]) -> None:
    for line in lines:
        print(line)
    print()


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


def format_strikethrough(text: str) -> str:
    if _plain_mode:
        return text
    return f"{_c(STRIKE)}{_c(DIM)}{text}{_reset()}"


def format_nginx_status_badge(*, site_enabled: bool) -> str:
    if site_enabled:
        return status_badge("LIVE", "ok")
    return status_badge("OFF", "off")


def format_nginx_security(*, site_enabled: bool, ssl_enabled: bool) -> str:
    if not site_enabled:
        return f"{_c(DIM)}inactive — not loaded by nginx{_reset()}"
    if ssl_enabled:
        return f"{_c(GREEN)}HTTPS{_reset()} {_c(DIM)}encrypted traffic{_reset()}"
    return f"{_c(YELLOW)}HTTP only{_reset()} {_c(DIM)}no TLS on this site{_reset()}"


def format_nginx_exposure(ports: list[int]) -> str:
    if not ports:
        return f"{_c(DIM)}no listen ports found{_reset()}"
    port_text = ", ".join(str(port) for port in sorted(ports))
    if any(port in {80, 443, 8080, 8443} for port in ports):
        return f"{_c(GREEN)}PUBLIC{_reset()} {port_text}"
    return port_text


def print_info_card(
    *,
    badge: str,
    title: str,
    lines: list[str],
    tone: str = "ok",
    strike_title: bool = False,
) -> None:
    print_status_box(
        badge=badge,
        title=title,
        lines=lines,
        tone=tone,
        strike_title=strike_title,
    )


def cert_expiry_details(not_after: datetime | None) -> tuple[str, str, str, float, str]:
    if not_after is None:
        return (
            status_badge("UNKNOWN", "off"),
            "UNKNOWN",
            "expiry date unknown",
            0.0,
            "off",
        )

    now = datetime.now(timezone.utc)
    expiry = not_after if not_after.tzinfo else not_after.replace(tzinfo=timezone.utc)
    days = (expiry - now).days
    date_text = expiry.strftime("%Y-%m-%d")

    if days < 0:
        return (
            status_badge("EXPIRED", "bad"),
            "EXPIRED",
            f"expired on {date_text} ({abs(days)} days ago)",
            0.0,
            "bad",
        )
    if days <= 14:
        return (
            status_badge("RENEW SOON", "warn"),
            "RENEW SOON",
            f"valid until {date_text} ({days} days left)",
            max(5.0, (days / 90) * 100),
            "warn",
        )
    if days <= 30:
        return (
            status_badge("EXPIRING", "warn"),
            "EXPIRING",
            f"valid until {date_text} ({days} days left)",
            (days / 90) * 100,
            "warn",
        )

    return (
        status_badge("VALID", "ok"),
        "VALID",
        f"valid until {date_text} ({days} days left)",
        min(100.0, (days / 90) * 100),
        "ok",
    )


def process_load_details(
    cpu_percent: float | None,
    *,
    process_status: str | None = None,
) -> tuple[str, str]:
    """Map process state to badge + box tone.

    Lifecycle (psutil status):
      ZOMBIE / DEAD  -> red     broken process
      STOPPED        -> dim     not running
      WAITING        -> blue    sleeping or blocked on I/O

    CPU while runnable:
      IDLE           -> green   alive, almost no CPU
      WORKING        -> blue    normal active use
      HOT            -> yellow  heavy load
      BUSY           -> red     maxed out
    """
    status = (process_status or "running").lower()
    cpu = cpu_percent or 0.0

    if status == "zombie":
        return status_badge("ZOMBIE", "bad"), "bad"
    if status == "dead":
        return status_badge("DEAD", "bad"), "bad"
    if status in {"stopped", "tracing-stop"}:
        return status_badge("STOPPED", "off"), "off"
    if status in {"sleeping", "disk-sleep", "waking", "locked"}:
        return status_badge("WAITING", "work"), "work"
    if status == "idle":
        return status_badge("IDLE", "ok"), "ok"

    if cpu >= 75:
        return status_badge("BUSY", "bad"), "bad"
    if cpu >= 40:
        return status_badge("HOT", "warn"), "warn"
    if cpu >= 3:
        return status_badge("WORKING", "work"), "work"
    return status_badge("IDLE", "ok"), "ok"


def format_meter(
    label: str,
    percent: float,
    *,
    width: int = 22,
    label_width: int = 8,
) -> str:
    clamped = min(100.0, max(0.0, percent))
    bar = format_horizontal_bar(clamped, width=width)
    display = label if len(label) <= label_width else label[:label_width]
    gap = max(1, label_width - len(display))
    return f"{format_label(display.rstrip(':'))}{' ' * gap}[{bar}] {clamped:4.1f}%"


def format_memory_meter(
    memory_bytes: int | None,
    system_total_bytes: int,
    *,
    width: int = 22,
) -> str:
    if memory_bytes is None or system_total_bytes <= 0:
        bar = format_horizontal_bar(0.0, width=width)
        return f"{format_label('RAM')}     [{bar}] unknown"

    percent = min(100.0, (memory_bytes / system_total_bytes) * 100)
    bar = format_horizontal_bar(percent, width=width)
    return (
        f"{format_label('RAM')}     [{bar}] {format_bytes(memory_bytes)}"
        f"  {_c(DIM)}({percent:.1f}% of server RAM){_reset()}"
    )


def format_cron_schedule_hint(expression: str) -> str:
    parts = expression.split()
    if len(parts) != 5:
        return expression

    minute, hour, day, month, weekday = parts
    if minute.startswith("*/"):
        return f"every {minute[2:]} minutes"
    if hour.startswith("*/"):
        return f"every {hour[2:]} hours"
    if minute == "0" and hour == "*":
        return "every hour"
    if minute == "0" and hour != "*" and day == "*" and month == "*":
        return f"daily at {hour.zfill(2)}:00"
    if minute != "*" and hour != "*" and day == "*" and month == "*":
        return f"daily at {hour.zfill(2)}:{minute.zfill(2)}"
    if day != "*":
        return f"day {day} of month at {hour.zfill(2)}:{minute.zfill(2)}"
    return expression


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
