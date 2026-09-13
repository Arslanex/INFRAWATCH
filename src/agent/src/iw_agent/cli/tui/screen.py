"""A row buffer that repaints only what changed.

The editor redraws on every keypress. Rewriting the whole screen each time
flickers and floods a slow SSH link, so the screen keeps the last frame and
emits just the rows that differ.

Writing goes through an injected callable, which is what makes frames
assertable in tests without a terminal.
"""
from __future__ import annotations

from typing import Callable

from iw_agent.cli.output import pad_visible, truncate_visible
from iw_agent.cli.tui.terminal import CLEAR_LINE, cursor_to


class Screen:
    def __init__(
        self,
        write: Callable[[str], None],
        *,
        width: int,
        height: int,
    ) -> None:
        self._write = write
        self.width = width
        self.height = height
        self._rows = [""] * height
        self._painted: list[str | None] = [None] * height

    # -- buffer ------------------------------------------------------------

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._rows = [""] * height
        self.invalidate()

    def invalidate(self) -> None:
        """Forget what is on screen, so the next flush repaints everything."""
        self._painted = [None] * self.height

    def clear(self) -> None:
        self._rows = [""] * self.height

    def set_row(self, index: int, text: str) -> None:
        if 0 <= index < self.height:
            self._rows[index] = truncate_visible(text, self.width)

    def set_rows(self, start: int, lines) -> None:
        for offset, text in enumerate(lines):
            self.set_row(start + offset, text)

    def row(self, index: int) -> str:
        return self._rows[index]

    # -- output ------------------------------------------------------------

    def flush(self) -> None:
        chunks: list[str] = []
        for index, text in enumerate(self._rows):
            if self._painted[index] == text:
                continue
            chunks.append(cursor_to(index + 1, 1) + CLEAR_LINE + text)
            self._painted[index] = text
        if chunks:
            self._write("".join(chunks))

    def snapshot(self) -> list[str]:
        """The current frame as plain rows — the shape tests assert against."""
        return [pad_visible(text, self.width).rstrip() for text in self._rows]
