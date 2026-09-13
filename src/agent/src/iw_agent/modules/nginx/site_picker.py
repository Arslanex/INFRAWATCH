"""Full-screen site picker for ``iw nginx -i``.

Compact cards (domain, why, security, certificate) with arrow-key navigation.
**New site** is always first; ``q`` quits.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Union

from iw_agent.cli.output import (
    BOLD,
    DIM,
    _c,
    _reset,
    format_field,
    format_nginx_security,
    format_strikethrough,
    highlight_row,
    truncate_visible,
)
from iw_agent.cli.tui.keys import Key, ctrl, decode
from iw_agent.cli.tui.screen import Screen
from iw_agent.cli.tui.terminal import Terminal, supports_fullscreen
from iw_agent.modules.nginx.schemas import SiteProfile, VirtualHost

PickResult = Optional[Union[VirtualHost, Literal["__new__"]]]

FOOTER = "↑↓ select  enter open  q quit"

_SSL_LABELS = {
    "no_ssl": "no SSL",
    "ssl_ok": "HTTPS ok",
    "ssl_expiring": "expiring",
    "ssl_expired": "expired",
    "ssl_mismatch": "mismatch",
    "ssl_orphan": "orphan",
}


class SitePickerUnavailable(Exception):
    """Raised when the terminal cannot host the picker."""


@dataclass
class _Card:
    kind: Literal["new", "site"]
    lines: list[str]
    profile: SiteProfile | None = None


@dataclass
class SitePickerSession:
    cards: list[_Card]
    summary: str
    dry_run: bool = False
    cursor: int = 0
    top: int = 0
    status: str = ""
    running: bool = True
    result: PickResult = None

    @classmethod
    def from_profiles(
        cls,
        profiles: list[SiteProfile],
        *,
        summary: str,
        dry_run: bool = False,
    ) -> SitePickerSession:
        cards = [_new_site_card()]
        for profile in profiles:
            cards.append(_site_card(profile))
        return cls(cards=cards, summary=summary, dry_run=dry_run)

    def _card_lines(self, index: int) -> list[str]:
        return self.cards[index].lines

    def frame_lines(self, width: int, height: int) -> list[str]:
        header = f" {_c(BOLD)}Websites (nginx){_reset()}  {_c(DIM)}pick a site to edit{_reset()}"
        flags = []
        if self.dry_run:
            flags.append(f"{_c(DIM)}dry-run{_reset()}")
        if flags:
            header = truncate_visible(f"{header}  {' '.join(flags)}", width)

        lines = [truncate_visible(header, width), truncate_visible(f" {_c(DIM)}{self.summary}{_reset()}", width), ""]

        body_rows = max(1, height - 3)
        visible_cards = _visible_card_count(body_rows)
        self.top = _clamp_top(self.top, self.cursor, visible_cards, len(self.cards))

        used = 2
        for offset in range(visible_cards):
            index = self.top + offset
            if index >= len(self.cards):
                break
            selected = index == self.cursor
            for card_line in self._card_lines(index):
                if used >= body_rows + 2:
                    break
                line = truncate_visible(card_line, width)
                lines.append(highlight_row(line, selected=selected, width=width))
                used += 1
            if used < body_rows + 2 and index + 1 < len(self.cards):
                lines.append("")
                used += 1

        while len(lines) < height - 1:
            lines.append("")
        footer = self.status or FOOTER
        lines.append(truncate_visible(f" {_c(DIM)}{footer}{_reset()}", width))
        return lines[:height]

    def handle(self, event) -> None:
        if event in ("q", ctrl("c"), Key.ESCAPE):
            self.result = None
            self.running = False
            return
        if event in (Key.DOWN, "j"):
            self.cursor = min(len(self.cards) - 1, self.cursor + 1)
            self.status = ""
        elif event in (Key.UP, "k"):
            self.cursor = max(0, self.cursor - 1)
            self.status = ""
        elif event is Key.ENTER:
            if self.cards[self.cursor].kind == "new":
                self.result = "__new__"
            else:
                self.result = self.cards[self.cursor].profile.virtual_host
            self.running = False


def _compact_card_lines(title: str, body: list[str], *, strike_title: bool = False) -> list[str]:
    bar = f"{_c(DIM)}│{_reset()}"
    display_title = format_strikethrough(title) if strike_title else f"{_c(BOLD)}{title}{_reset()}"
    lines = [f" {bar} {display_title}"]
    for line in body:
        lines.append(f" {bar} {line}")
    return lines


def _new_site_card() -> _Card:
    lines = _compact_card_lines(
        "Create a new site",
        [format_field("Next", "minimal skeleton → structural editor")],
    )
    return _Card(kind="new", lines=lines)


def _site_card(profile: SiteProfile) -> _Card:
    host = profile.virtual_host
    why = (
        "nginx loaded and serves this config"
        if host.enabled
        else "in sites-available but not linked in sites-enabled"
    )
    ssl_label = _SSL_LABELS.get(profile.ssl_status.value, profile.ssl_status.value)
    body = [
        format_field("Why", why),
        format_field(
            "Security",
            format_nginx_security(
                site_enabled=host.enabled,
                ssl_enabled=host.ssl_enabled,
            ),
        ),
        format_field("Certificate", ssl_label),
    ]
    title = ", ".join(host.server_names) or host.config_path.rsplit("/", 1)[-1] or "(unnamed site)"
    lines = _compact_card_lines(title, body, strike_title=not host.enabled)
    return _Card(kind="site", lines=lines, profile=profile)


def _visible_card_count(body_rows: int) -> int:
    # title + 3 fields + blank separator ≈ 5 lines per card
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


async def pick_site(
    profiles: list[SiteProfile],
    *,
    summary: str,
    dry_run: bool = False,
    terminal: Terminal | None = None,
) -> PickResult:
    session = SitePickerSession.from_profiles(
        profiles,
        summary=summary,
        dry_run=dry_run,
    )
    if terminal is None and not supports_fullscreen():
        raise SitePickerUnavailable(
            "the site picker needs an interactive terminal",
        )

    owned = terminal is None
    term = terminal or Terminal()
    context = term if owned else _NullContext(term)

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
                return None
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
                session.handle(event)
                if not session.running:
                    break

    return session.result


class _NullContext:
    def __init__(self, value):
        self._value = value

    def __enter__(self):
        return self._value

    def __exit__(self, *_exc):
        return False
