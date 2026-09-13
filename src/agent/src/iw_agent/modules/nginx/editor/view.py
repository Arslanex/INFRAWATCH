"""Compose the editor frame into a :class:`Screen`.

Kept free of terminal and input concerns so a frame can be rendered into a
fake screen and asserted line by line.
"""
from __future__ import annotations

from dataclasses import dataclass

from iw_agent.cli.output import BOLD, DIM, _c, _reset, highlight_row, pad_visible, truncate_visible
from iw_agent.modules.nginx.confparse import Block, Comment, Directive, Raw
from iw_agent.modules.nginx.editor.hints import hint_for_row
from iw_agent.modules.nginx.editor.rows import Row, RowKind

RIGHT_PANE_WIDTH = 42
MIN_SPLIT_WIDTH = 86
MIN_HEIGHT = 8

GUTTER = 5

_GREEN = "\033[32m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"

FOOTER_HINTS = (
    "↑↓ move  o on/off  enter edit  a add  s save  x actions  / search  ? help  q quit"
)

HELP_LINES = [
    "Navigation",
    "  ↑↓ j/k      move between rows",
    "  → l         expand block",
    "  ← h         collapse block",
    "  g / G       top / bottom",
    "  PgUp/Dn     page scroll",
    "",
    "Editing",
    "  Enter       edit row (form or raw)",
    "  e           raw line edit",
    "  a / A       add after / add inside block",
    "  d           delete",
    "  u / Ctrl+Z  undo",
    "  Ctrl+R      redo",
    "",
    "Site",
    "  o           enable or disable this site (symlink + reload)",
    "",
    "File",
    "  s           save (nginx -t + write)",
    "  x           actions (reload, HTTPS, …)",
    "",
    "Search",
    "  /           search in config",
    "  n / N       next / previous match",
    "",
    "Other",
    "  ?           this help",
    "  q           quit",
]


@dataclass
class Modal:
    title: str
    widget: object


@dataclass
class Frame:
    title: str
    path: str
    rows: list[Row]
    cursor: int
    top: int
    dirty_count: int = 0
    status: str = ""
    read_only: bool = False
    dry_run: bool = False
    site_enabled: bool = True
    search_label: str = ""
    modal: Modal | None = None


def body_height(height: int) -> int:
    """Rows available for the file pane, after the header and footer."""
    return max(1, height - 2)


def clamp_scroll(top: int, cursor: int, visible: int, total: int, *, margin: int = 3) -> int:
    """Keep the cursor inside the viewport with a little breathing room."""
    if total <= visible:
        return 0
    top = min(top, max(0, total - visible))
    if cursor < top + margin:
        top = max(0, cursor - margin)
    if cursor > top + visible - 1 - margin:
        top = min(max(0, total - visible), cursor - visible + 1 + margin)
    return max(0, min(top, max(0, total - visible)))


def _uses_inline_modal(modal: Modal | None) -> bool:
    if modal is None:
        return False
    from iw_agent.cli.tui.widgets import LineEditor, Picker

    return isinstance(modal.widget, (LineEditor, Picker))


def render(screen, frame: Frame) -> None:
    width, height = screen.width, screen.height
    screen.clear()

    if height < MIN_HEIGHT or width < 40:
        screen.set_row(0, "terminal too small — needs at least 40x8")
        return

    split = width >= MIN_SPLIT_WIDTH
    left_width = width - RIGHT_PANE_WIDTH - 1 if split else width
    inline = split and _uses_inline_modal(frame.modal)

    screen.set_row(0, _header(frame, width))

    visible = body_height(height)
    if inline:
        detail = _detail_lines(frame, editing=True)
        left_lines = _left_pane_lines(frame, left_width, visible)
    elif frame.modal is not None and split:
        detail = _modal_lines(frame.modal, RIGHT_PANE_WIDTH, visible)
        left_lines = _left_pane_lines(frame, left_width, visible)
    elif split:
        detail = _detail_lines(frame)
        left_lines = _left_pane_lines(frame, left_width, visible)
    else:
        detail = []
        left_lines = _left_pane_lines(frame, left_width, visible)

    if not split and frame.modal is not None and not inline:
        for offset, line in enumerate(left_lines[:visible]):
            screen.set_row(offset + 1, line)
        overlay = _modal_lines(frame.modal, width, visible)
        start = height - 1 - min(len(overlay), visible // 2)
        for offset, line in enumerate(overlay[-min(len(overlay), visible // 2) :]):
            screen.set_row(start + offset, line)
        screen.set_row(height - 1, _footer(frame, width))
        return

    for offset in range(visible):
        left = left_lines[offset] if offset < len(left_lines) else ""
        if not split:
            screen.set_row(offset + 1, left)
            continue
        right = detail[offset] if offset < len(detail) else ""
        screen.set_row(
            offset + 1,
            pad_visible(left, left_width) + f"{_c(DIM)}│{_reset()}" + right,
        )

    screen.set_row(height - 1, _footer(frame, width))


def _header(frame: Frame, width: int) -> str:
    flags = []
    if frame.site_enabled:
        flags.append(f"{_c(_GREEN)}● LIVE{_reset()}")
    else:
        flags.append(f"{_c(DIM)}○ OFF{_reset()}")
    if frame.dry_run:
        flags.append(f"{_c(_YELLOW)}dry-run{_reset()}")
    if frame.read_only:
        flags.append(f"{_c(_YELLOW)}read-only{_reset()}")
    if frame.search_label:
        flags.append(f"{_c(_BLUE)}search: {frame.search_label}{_reset()}")
    if frame.dirty_count:
        flags.append(f"{_c(_YELLOW)}● {frame.dirty_count} unsaved{_reset()}")
    tail = "  ".join(flags)
    head = f"{_c(BOLD)}{frame.title}{_reset()}  {_c(DIM)}{frame.path}{_reset()}"
    return truncate_visible(f" {head}  {tail}", width)


def _footer(frame: Frame, width: int) -> str:
    text = frame.status or FOOTER_HINTS
    return truncate_visible(f"{_c(DIM)} {text}{_reset()}", width)


def _left_pane_lines(frame: Frame, width: int, visible: int) -> list[str]:
    from iw_agent.cli.tui.widgets import LineEditor, Picker

    out: list[str] = []
    index = frame.top
    while len(out) < visible and index < len(frame.rows):
        if (
            index == frame.cursor
            and frame.modal is not None
            and isinstance(frame.modal.widget, LineEditor)
        ):
            out.append(_inline_editor_row(frame, width))
            index += 1
            continue
        if (
            index == frame.cursor
            and frame.modal is not None
            and isinstance(frame.modal.widget, Picker)
        ):
            remaining = visible - len(out)
            picker_lines = _inline_picker_rows(frame.modal.widget, width, remaining)
            out.extend(picker_lines)
            index += 1
            continue
        selected = index == frame.cursor and frame.modal is None
        out.append(_row_text(frame.rows[index], selected=selected, width=width))
        index += 1
    while len(out) < visible:
        out.append("")
    return out[:visible]


def _row_text(row: Row, *, selected: bool, width: int, editing: bool = False) -> str:
    number = f"{row.line_no:>4} " if row.line_no else "   · "
    marker = "▸" if selected or editing else " "

    if row.kind is RowKind.ADD_SLOT:
        body = f"{'  ' * row.depth}{_c(_GREEN)}{row.text}{_reset()}"
    elif row.kind is RowKind.BLOCK_FOLDED:
        body = f"{_c(_CYAN)}{row.text}{_reset()}"
    elif row.kind is RowKind.COMMENT:
        body = f"{_c(DIM)}{row.text}{_reset()}"
    elif row.kind is RowKind.RAW:
        body = f"{_c(_YELLOW)}{row.text}{_reset()}"
    elif row.kind in (RowKind.BLOCK_OPEN, RowKind.BLOCK_CLOSE):
        body = f"{_c(_CYAN)}{row.text}{_reset()}"
    else:
        body = row.text

    line = f"{_c(DIM)}{number}{_reset()}{marker} {body}"
    if editing:
        return truncate_visible(highlight_row(line, editing=True, width=width), width)
    if selected:
        return truncate_visible(highlight_row(line, selected=True, width=width), width)
    return truncate_visible(line, width)


def _inline_editor_row(frame: Frame, width: int) -> str:
    from iw_agent.cli.tui.widgets import LineEditor

    widget = frame.modal.widget
    assert isinstance(widget, LineEditor)
    row = frame.rows[frame.cursor]
    number = f"{row.line_no:>4} " if row.line_no else "   · "
    prefix = f"{_c(DIM)}{number}{_reset()}▸ "
    field = widget.display(max(8, width - 12))
    line = f"{prefix}{_c(BOLD)}{field}{_reset()}"
    return truncate_visible(highlight_row(line, editing=True, width=width), width)


def _inline_picker_rows(picker, width: int, max_rows: int) -> list[str]:
    lines = [truncate_visible(highlight_row(f" {_c(_GREEN)}filter:{_reset()} {picker.filter}█", editing=True, width=width), width)]
    for item_line in picker.lines(max(1, max_rows - 2)):
        styled = f" {item_line}"
        lines.append(truncate_visible(highlight_row(styled, editing=True, width=width), width))
    lines.append(truncate_visible(highlight_row(f" {_c(DIM)}↑↓ pick  enter add  esc cancel{_reset()}", editing=True, width=width), width))
    return lines[:max_rows]


def _modal_lines(modal: Modal, width: int, height: int) -> list[str]:
    from iw_agent.cli.tui.widgets import Confirm, LineEditor, Picker, Viewer

    widget = modal.widget
    lines = [
        "",
        f" {_c(_YELLOW)}{modal.title}{_reset()}",
        f" {_c(DIM)}{'─' * max(1, width - 2)}{_reset()}",
    ]

    if isinstance(widget, LineEditor):
        lines.append(f" {widget.display(width - 3)}")
        lines.append("")
        if widget.hint:
            lines += [f" {_c(DIM)}{chunk}{_reset()}" for chunk in _wrap(widget.hint, width - 2)]
        lines += ["", f" {_c(DIM)}enter{_reset()} save   {_c(DIM)}esc{_reset()} cancel"]
    elif isinstance(widget, Picker):
        lines.append(f" {_c(DIM)}filter:{_reset()} {widget.filter}█")
        lines.append("")
        lines += widget.lines(max(1, height - 8))
        lines += ["", f" {_c(DIM)}↑↓{_reset()} pick   {_c(DIM)}enter{_reset()} add   {_c(DIM)}esc{_reset()} cancel"]
    elif isinstance(widget, Viewer):
        for line in widget.lines(max(1, height - 5)):
            tone = _GREEN if line.startswith("+") else _YELLOW if line.startswith("-") else DIM
            lines.append(f" {_c(tone)}{line}{_reset()}")
        lines += ["", f" {_c(DIM)}↑↓{_reset()} scroll   {_c(DIM)}esc{_reset()} close"]
    elif isinstance(widget, Confirm):
        lines += [f" {chunk}" for chunk in _wrap(widget.question, width - 2)]
        lines.append("")
        if widget.require_word:
            lines.append(f" type {widget.require_word}: {widget.typed}█")
        else:
            lines.append(f" {_c(DIM)}y{_reset()} yes   {_c(DIM)}n{_reset()} no")
    return lines


def _detail_lines(frame: Frame, *, editing: bool = False) -> list[str]:
    if not frame.rows:
        return []
    row = frame.rows[min(frame.cursor, len(frame.rows) - 1)]
    hint = hint_for_row(row)
    width = RIGHT_PANE_WIDTH - 2
    lines = [
        "",
        f" {_c(_CYAN)}{hint.title}{_reset()}",
        f" {_c(DIM)}{'─' * width}{_reset()}",
    ]

    if isinstance(row.node, Directive):
        value = " ".join(row.node.args) or "(no value)"
        lines.append(f" {_c(BOLD)}now{_reset()} {_c(DIM)}{_truncate(value, width - 4)}{_reset()}")
        lines.append("")

    lines += _panel_section("What", hint.what, width)
    lines += _panel_section("Changes", hint.changes, width)
    lines += _panel_section("Add here", hint.add_here, width)

    if editing and frame.modal is not None:
        lines += _panel_section("Editing", "Type in the config pane on the left — this side is reference only.", width)

    dim, reset = _c(DIM), _reset()
    if row.kind is RowKind.ADD_SLOT:
        keys = f"{dim}enter{reset} pick template  {dim}a{reset} same"
    elif isinstance(row.node, Block) and row.kind is RowKind.BLOCK_OPEN:
        keys = f"{dim}enter{reset} edit header  {dim}->{reset} expand  {dim}a{reset} add inside"
    else:
        keys = f"{dim}enter{reset} edit  {dim}a{reset} add after  {dim}d{reset} delete"

    lines += ["", f" {keys}"]
    return lines


def _panel_section(label: str, text: str, width: int) -> list[str]:
    body = _wrap(text, width)
    if not body:
        return []
    out = [f" {_c(BOLD)}{label}{_reset()}"]
    out.extend(f" {_c(DIM)}{chunk}{_reset()}" for chunk in body)
    out.append("")
    return out


def _truncate(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return f"{text[: max(0, width - 1)]}…"


def _wrap(text: str, width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    out, current = [], words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            out.append(current)
            current = word
    out.append(current)
    return out
