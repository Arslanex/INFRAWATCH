from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Any, Callable, Sequence

from iw_agent.core.schemas import AgentModel


def print_banner() -> None:
    print(
        "\n"
        "  InfraWatch Agent\n"
        "  ─────────────────────────────────────\n"
        "  Type a command, e.g.  iw device  ·  iw ports  ·  iw containers\n"
    )


def print_heading(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def print_summary(pairs: list[tuple[str, str]]) -> None:
    width = max(len(label) for label, _ in pairs) if pairs else 0
    for label, value in pairs:
        print(f"{label:<{width}}  {value}")


def print_table(
    headers: list[str],
    rows: list[list[str]],
    *,
    widths: list[int] | None = None,
) -> None:
    if not rows:
        print("  (none)")
        return

    if widths is None:
        widths = [
            max(len(headers[index]), *(len(row[index]) for row in rows))
            for index in range(len(headers))
        ]

    header_line = "  ".join(
        header.ljust(widths[index]) for index, header in enumerate(headers)
    )
    print(header_line)
    print("  ".join("-" * widths[index] for index in range(len(headers))))

    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def print_result_count(noun: str, count: int) -> None:
    label = noun if count == 1 else f"{noun}s"
    print(f"\n{count} {label}")


def format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    if value < 1024:
        return f"{value} B"
    if value < 1024 ** 2:
        return f"{value / 1024:.1f} KB"
    if value < 1024 ** 3:
        return f"{value / (1024 ** 2):.1f} MB"
    return f"{value / (1024 ** 3):.1f} GB"


def format_percent(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.1f}%"


def format_optional(value: Any, *, fallback: str = "-") -> str:
    if value is None:
        return fallback
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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
    render: Callable[[Any], None],
) -> None:
    if json_output:
        emit_json(payload)
        return
    render(payload)
