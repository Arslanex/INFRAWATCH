"""Full-screen arrow-key picker for compact status-box cards."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Mapping, Optional, TypeVar

from iw_agent.cli.output import BOLD, DIM, _c, _reset, highlight_row, truncate_visible
from iw_agent.cli.tui.keys import Key, ctrl, decode
from iw_agent.cli.tui.screen import Screen
from iw_agent.cli.tui.terminal import Terminal, supports_fullscreen

T = TypeVar("T")

DEFAULT_FOOTER = "↑↓ select  enter open  q quit"
LIST_FOOTER = "↑↓ select  enter manage  q quit"
HUB_FOOTER = "↑↓ select  enter run  b back  q quit"
BACK_KEYS = frozenset({"b", "back"})


@dataclass
class PickResult(Generic[T]):
    value: Optional[T] = None
    quit_session: bool = False
    action: str = "select"

    @property
    def back(self) -> bool:
        return self.value is None and not self.quit_session


class CardPickerUnavailable(Exception):
    """Raised when the terminal cannot host the picker."""


@dataclass
class CardItem(Generic[T]):
    lines: list[str]
    value: T
    footer: str = ""
    keys: Mapping[str, str] = field(default_factory=dict)
    """Extra single-key shortcuts this card answers to, as ``key -> action name``."""


@dataclass
class CardPickerSession(Generic[T]):
    title: str
    subtitle: str
    items: list[CardItem[T]]
    summary: str = ""
    footer: str = DEFAULT_FOOTER
    dry_run: bool = False
    key_hints: Mapping[str, str] = field(default_factory=dict)
    """Status shown when an extra key is pressed on a card that ignores it."""
    cursor: int = 0
    top: int = 0
    status: str = ""
    running: bool = True
    result: Optional[T] = None
    action: str = "select"
    quit_session: bool = False

    def current_footer(self) -> str:
        if self.items and self.items[self.cursor].footer:
            return self.items[self.cursor].footer
        return self.footer

    def frame_lines(self, width: int, height: int) -> list[str]:
        header = f" {_c(BOLD)}{self.title}{_reset()}  {_c(DIM)}{self.subtitle}{_reset()}"
        if self.dry_run:
            header = truncate_visible(f"{header}  {_c(DIM)}dry-run{_reset()}", width)

        lines = [truncate_visible(header, width)]
        if self.summary:
            lines.append(truncate_visible(f" {_c(DIM)}{self.summary}{_reset()}", width))
        lines.append("")

        body_rows = max(1, height - 3)
        visible_cards = _visible_card_count(body_rows)
        self.top = _clamp_top(self.top, self.cursor, visible_cards, len(self.items))

        used = len(lines)
        for offset in range(visible_cards):
            index = self.top + offset
            if index >= len(self.items):
                break
            selected = index == self.cursor
            for card_line in self.items[index].lines:
                if used >= height - 1:
                    break
                line = truncate_visible(card_line, width)
                lines.append(highlight_row(line, selected=selected, width=width))
                used += 1
            if used < height - 1 and index + 1 < len(self.items):
                lines.append("")
                used += 1

        while len(lines) < height - 1:
            lines.append("")
        footer = self.status or self.current_footer()
        lines.append(truncate_visible(f" {_c(DIM)}{footer}{_reset()}", width))
        return lines[:height]

    def handle(self, event, *, back_keys: frozenset = frozenset()) -> None:
        if event in ("q", ctrl("c")):
            self._finish(quit_session=True)
            return
        if event in back_keys:
            self._finish(quit_session=False)
            return
        if event is Key.ESCAPE:
            # Escape leaves the level when there is one to leave, else the picker.
            self._finish(quit_session=not back_keys)
            return
        if event in (Key.DOWN, "j"):
            self.cursor = min(len(self.items) - 1, self.cursor + 1)
            self._clear_status()
        elif event in (Key.UP, "k"):
            self.cursor = max(0, self.cursor - 1)
            self._clear_status()
        elif event is Key.ENTER:
            if self.items:
                self.result = self.items[self.cursor].value
                self.action = "select"
            self.running = False
        elif isinstance(event, str) and event in self.key_hints:
            self._handle_extra_key(event)

    def _handle_extra_key(self, key: str) -> None:
        card = self.items[self.cursor] if self.items else None
        if card is None or key not in card.keys:
            self.status = self.key_hints[key]
            return
        self.result = card.value
        self.action = card.keys[key]
        self.running = False

    def _finish(self, *, quit_session: bool) -> None:
        self.result = None
        self.quit_session = quit_session
        self.running = False

    def _clear_status(self) -> None:
        # Warnings stay pinned while the user moves around; plain hints do not.
        if not self.status.startswith("!"):
            self.status = ""


def _visible_card_count(body_rows: int) -> int:
    return max(1, body_rows // 6 + 1)


def _clamp_top(top: int, cursor: int, visible: int, total: int) -> int:
    if total <= visible:
        return 0
    top = max(0, min(top, total - visible))
    if cursor < top:
        return cursor
    if cursor >= top + visible:
        return cursor - visible + 1
    return top


async def pick_card(
    items: list[CardItem[T]],
    *,
    title: str,
    subtitle: str,
    summary: str = "",
    footer: str = DEFAULT_FOOTER,
    dry_run: bool = False,
    status: str = "",
    key_hints: Mapping[str, str] | None = None,
    back_keys: frozenset | None = None,
    terminal: Terminal | None = None,
) -> PickResult[T]:
    if not items:
        return PickResult()

    session = CardPickerSession(
        title=title,
        subtitle=subtitle,
        items=items,
        summary=summary,
        footer=footer,
        dry_run=dry_run,
        key_hints=key_hints or {},
        status=status,
    )
    if terminal is None and not supports_fullscreen():
        raise CardPickerUnavailable("the picker needs an interactive terminal")

    owned = terminal is None
    term = terminal or Terminal()
    context = term if owned else _NullContext(term)
    back = back_keys or frozenset()

    with context:
        width, height = term.size()
        screen = Screen(term.write, width=width, height=height)
        pending = b""

        while session.running:
            new_width, new_height = term.size()
            if (new_width, new_height) != (screen.width, screen.height):
                screen.resize(new_width, new_height)
            frame = session.frame_lines(screen.width, screen.height)
            screen.set_rows(0, frame)
            screen.flush()

            try:
                chunk = term.read()
            except KeyboardInterrupt:
                return PickResult(quit_session=True)
            if not chunk:
                continue

            pending += chunk
            events, pending = decode(pending)
            if pending == b"\x1b":
                tail = term.wait_for_escape_tail()
                if tail:
                    pending += tail
                    events, pending = decode(pending)
                else:
                    events.append(Key.ESCAPE)
                    pending = b""

            for event in events:
                session.handle(event, back_keys=back)
                if not session.running:
                    break

    return PickResult(
        value=session.result,
        quit_session=session.quit_session,
        action=session.action,
    )


class _NullContext:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, *_exc):
        return False
