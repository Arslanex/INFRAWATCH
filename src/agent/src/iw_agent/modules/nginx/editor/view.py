"""Compose the editor frame into a :class:`Screen`.

Kept free of terminal and input concerns so a frame can be rendered into a
fake screen and asserted line by line.
"""
from __future__ import annotations

from dataclasses import dataclass

from iw_agent.cli.output import BOLD, DIM, _c, _reset, pad_visible, truncate_visible
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
_REVERSE = "\033[7m"

FOOTER_HINTS = (
    "↑↓ move  → open  ← close  enter edit  a add  s save  x actions  / search  ? help  q quit"
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


def render(screen, frame: Frame) -> None:
    width, height = screen.width, screen.height
    screen.clear()

    if height < MIN_HEIGHT or width < 40:
        screen.set_row(0, "terminal too small — needs at least 40x8")
        return

    split = width >= MIN_SPLIT_WIDTH
    left_width = width - RIGHT_PANE_WIDTH - 1 if split else width

    screen.set_row(0, _header(frame, width))

    visible = body_height(height)
    if frame.modal is not None:
        panel = _modal_lines(frame.modal, RIGHT_PANE_WIDTH if split else width, visible)
    else:
        panel = _detail_lines(frame) if split else []
    detail = panel

    if not split and frame.modal is not None:
        # no room for a side panel: the modal takes the bottom of the screen
        for offset in range(visible):
            index = frame.top + offset
            text = ""
            if index < len(frame.rows):
                text = _row_text(frame.rows[index], index == frame.cursor, width)
            screen.set_row(offset + 1, text)
        for offset, line in enumerate(panel[-min(len(panel), visible):]):
            screen.set_row(height - 1 - len(panel) + offset, line)
        screen.set_row(height - 1, _footer(frame, width))
        return

    for offset in range(visible):
        index = frame.top + offset
        left = ""
        if index < len(frame.rows):
            left = _row_text(frame.rows[index], index == frame.cursor, left_width)
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


def _row_text(row: Row, selected: bool, width: int) -> str:
    number = f"{row.line_no:>4} " if row.line_no else "   · "
    marker = "▸" if selected else " "

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
    if selected:
        line = f"{_c(_REVERSE)}{pad_visible(line, width)}{_reset()}"
    return truncate_visible(line, width)


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


def _detail_lines(frame: Frame) -> list[str]:
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
