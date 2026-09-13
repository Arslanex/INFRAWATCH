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
STRIKE = "\033[9m"

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


def format_horizontal_bar(percent: float, *, width: int = 28) -> str:
    filled = min(width, max(0, int(round(width * percent / 100))))
    full, _, empty = _bar_chars()
    color = _usage_color(percent)
    return (
        f"{_c(color)}{full * filled}{_reset()}"
        f"{_c(DIM)}{empty * (width - filled)}{_reset()}"
    )


def format_cpu_line(percent: float | None, cores: int | None) -> str:
    if percent is None:
        return "unknown"
    core_text = f"{cores} cores" if cores is not None else "cores unknown"
    color = _usage_color(percent)
    return f"{_c(color)}{format_percent(percent)}{_reset()} across {core_text}"


def format_cpu_core_grid(percents: list[float], *, bar_height: int = 6) -> list[str]:
    if not percents:
        return ["unknown"]

    full, partial, empty = _bar_chars()
    gap = "   "
    lines: list[str] = []

    lines.append(f"{_c(DIM)}{gap.join(f'C{index}' for index in range(len(percents)))}{_reset()}")

    for row in range(bar_height, 0, -1):
        threshold_low = ((row - 1) / bar_height) * 100
        threshold_high = (row / bar_height) * 100
        cells: list[str] = []
        for percent in percents:
            if percent >= threshold_high:
                cells.append(f"{_c(_usage_color(percent))}{full}{_reset()}")
            elif percent > threshold_low:
                cells.append(f"{_c(_usage_color(percent))}{partial}{_reset()}")
            else:
                cells.append(f"{_c(DIM)}{empty}{_reset()}")
        lines.append(gap.join(cells))

    lines.append(gap.join(format_percent(percent, colorize=True) for percent in percents))

    average = sum(percents) / len(percents)
    lines.append(
        f"{_c(DIM)}average{_reset()} {format_percent(average, colorize=True)}"
        f" {_c(DIM)}({len(percents)} cores){_reset()}"
    )
    return lines


def format_memory_bar(used: int | None, total: int | None, *, width: int = 28) -> list[str]:
    if used is None or total is None or total <= 0:
        return ["unknown"]

    percent = (used / total) * 100
    bar = format_horizontal_bar(percent, width=width)
    return [
        f"{format_bytes(used)} of {format_bytes(total)} ({percent:.0f}% full)",
        f"[{bar}]",
    ]


def format_load_panel(
    load_1: float | None,
    load_5: float | None,
    load_15: float | None,
    cores: int | None,
    *,
    width: int = 28,
) -> list[str]:
    if load_1 is None:
        return ["unknown"]

    lines = [format_load_line(load_1, load_5, load_15)]
    if cores and cores > 0:
        percent = min(100.0, (load_1 / cores) * 100)
        lines.append(f"[{format_horizontal_bar(percent, width=width)}]")
    return lines


def format_disk_bars(
    partitions: list[tuple[str, int, int]],
    *,
    width: int = 22,
) -> list[str]:
    if not partitions:
        return ["unknown"]

    readable = [
        (mount, used, total)
        for mount, used, total in partitions
        if total > 0
    ]
    if not readable:
        return ["unknown"]

    label_width = max(len(mount) for mount, _, _ in readable)
    lines: list[str] = []
    for mount, used, total in readable:
        percent = (used / total) * 100
        bar = format_horizontal_bar(percent, width=width)
        lines.append(
            f"{mount:<{label_width}}  [{bar}]  {percent:3.0f}%"
            f"  {_c(DIM)}{format_bytes(used)}/{format_bytes(total)}{_reset()}"
        )
    return lines


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
        return f"{_c(GREEN)}● LIVE{_reset()}" if not _plain_mode else "[LIVE]"
    return f"{_c(DIM)}○ OFF{_reset()}" if not _plain_mode else "[OFF]"


def format_nginx_security(*, site_enabled: bool, ssl_enabled: bool) -> str:
    if not site_enabled:
        return f"{_c(DIM)}inactive — not loaded by nginx{_reset()}"
    if ssl_enabled:
        lock = "LOCK" if _plain_mode else "🔒"
        return f"{_c(GREEN)}{lock} HTTPS{_reset()} {_c(DIM)}encrypted traffic{_reset()}"
    unlock = "OPEN" if _plain_mode else "🔓"
    return f"{_c(YELLOW)}{unlock} HTTP{_reset()} {_c(DIM)}no TLS on this site{_reset()}"


def format_nginx_exposure(ports: list[int]) -> str:
    if not ports:
        return f"{_c(DIM)}no listen ports found{_reset()}"
    port_text = ", ".join(str(port) for port in sorted(ports))
    if any(port in {80, 443, 8080, 8443} for port in ports):
        globe = "PUBLIC" if _plain_mode else "🌐"
        return f"{_c(CYAN)}{globe}{_reset()} {port_text}"
    return port_text


def print_site_card(
    *,
    site_enabled: bool,
    title: str,
    lines: list[str],
) -> None:
    tone = "ok" if site_enabled else "off"
    badge = format_nginx_status_badge(site_enabled=site_enabled)
    print_info_card(
        badge=badge,
        title=title,
        lines=lines,
        tone=tone,
        strike_title=not site_enabled,
    )


def print_info_card(
    *,
    badge: str,
    title: str,
    lines: list[str],
    tone: str = "ok",
    strike_title: bool = False,
) -> None:
    border_by_tone = {
        "ok": CYAN,
        "warn": YELLOW,
        "bad": RED,
        "off": DIM,
    }
    border = border_by_tone.get(tone, CYAN)
    display_title = format_strikethrough(title) if strike_title else title

    print(f"   {_c(border)}┌─ {badge}{_reset()}")
    print(f"   {_c(border)}│{_reset()} {display_title}")
    for line in lines:
        print(f"   {_c(border)}│{_reset()} {line}")
    print(f"   {_c(border)}└{'─' * 44}{_reset()}")
    print()


def cert_expiry_details(not_after: datetime | None) -> tuple[str, str, float, str]:
    if not_after is None:
        return (
            f"{_c(DIM)}? UNKNOWN{_reset()}",
            "expiry date unknown",
            0.0,
            "off",
        )

    now = datetime.now(timezone.utc)
    expiry = not_after if not_after.tzinfo else not_after.replace(tzinfo=timezone.utc)
    days = (expiry - now).days
    date_text = expiry.strftime("%Y-%m-%d")

    if days < 0:
        icon = "X" if _plain_mode else "❌"
        return (
            f"{_c(RED)}{icon} EXPIRED{_reset()}",
            f"expired on {date_text} ({abs(days)} days ago)",
            0.0,
            "bad",
        )
    if days <= 14:
        icon = "!" if _plain_mode else "⚠"
        return (
            f"{_c(YELLOW)}{icon} RENEW SOON{_reset()}",
            f"valid until {date_text} ({days} days left)",
            max(5.0, (days / 90) * 100),
            "warn",
        )
    if days <= 30:
        icon = "~" if _plain_mode else "⏳"
        return (
            f"{_c(YELLOW)}{icon} EXPIRING{_reset()}",
            f"valid until {date_text} ({days} days left)",
            (days / 90) * 100,
            "warn",
        )

    icon = "OK" if _plain_mode else "🔒"
    return (
        f"{_c(GREEN)}{icon} VALID{_reset()}",
        f"valid until {date_text} ({days} days left)",
        min(100.0, (days / 90) * 100),
        "ok",
    )


def process_load_details(cpu_percent: float | None) -> tuple[str, str]:
    cpu = cpu_percent or 0.0
    if cpu >= 50:
        badge = "BUSY" if _plain_mode else "🔥 BUSY"
        return f"{_c(RED)}{badge}{_reset()}", "bad"
    if cpu >= 10:
        badge = "ACTIVE" if _plain_mode else "⚡ ACTIVE"
        return f"{_c(YELLOW)}{badge}{_reset()}", "warn"
    badge = "IDLE" if _plain_mode else "💤 IDLE"
    return f"{_c(GREEN)}{badge}{_reset()}", "ok"


def format_meter(label: str, percent: float, *, width: int = 22) -> str:
    clamped = min(100.0, max(0.0, percent))
    bar = format_horizontal_bar(clamped, width=width)
    return f"{label:<4} [{bar}] {clamped:4.1f}%"


def format_memory_meter(
    memory_bytes: int | None,
    max_memory: int,
    *,
    width: int = 22,
) -> str:
    if not memory_bytes or max_memory <= 0:
        bar = format_horizontal_bar(0.0, width=width)
        return f"RAM  [{bar}] unknown"

    percent = min(100.0, (memory_bytes / max_memory) * 100)
    bar = format_horizontal_bar(percent, width=width)
    return f"RAM  [{bar}] {format_bytes(memory_bytes)}"


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
