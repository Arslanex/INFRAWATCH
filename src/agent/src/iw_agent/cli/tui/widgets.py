"""Small modal widgets: a one-line text field and a filterable picker.

Both are state machines with no terminal knowledge — they take key events and
produce lines — so the editor's interactive behaviour is testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from iw_agent.cli.tui.keys import Key, ctrl

CANCEL = object()
PENDING = object()


class LineEditor:
    """A single-line text field with a cursor."""

    def __init__(self, text: str = "", *, title: str = "", hint: str = "") -> None:
        self.title = title
        self.hint = hint
        self.text = text
        self.cursor = len(text)
        self.error = ""

    def handle(self, event):
        """Returns the text on commit, CANCEL on escape, PENDING otherwise."""
        self.error = ""
        if event is Key.ENTER:
            return self.text
        if event is Key.ESCAPE or event == ctrl("g"):
            return CANCEL
        if event is Key.BACKSPACE:
            if self.cursor:
                self.text = self.text[: self.cursor - 1] + self.text[self.cursor :]
                self.cursor -= 1
        elif event is Key.DELETE:
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1 :]
        elif event is Key.LEFT:
            self.cursor = max(0, self.cursor - 1)
        elif event is Key.RIGHT:
            self.cursor = min(len(self.text), self.cursor + 1)
        elif event is Key.HOME or event == ctrl("a"):
            self.cursor = 0
        elif event is Key.END or event == ctrl("e"):
            self.cursor = len(self.text)
        elif event == ctrl("u"):
            self.text = self.text[self.cursor :]
            self.cursor = 0
        elif event == ctrl("k"):
            self.text = self.text[: self.cursor]
        elif isinstance(event, str) and event >= " ":
            self.text = self.text[: self.cursor] + event + self.text[self.cursor :]
            self.cursor += len(event)
        return PENDING

    def display(self, width: int) -> str:
        """The text with a block cursor, scrolled to keep the caret visible."""
        window = max(8, width)
        start = max(0, self.cursor - window + 1)
        visible = self.text[start : start + window]
        offset = self.cursor - start
        return visible[:offset] + "█" + visible[offset:]


@dataclass
class PickerItem:
    label: str
    hint: str = ""
    value: object = None


class Picker:
    """A type-to-filter list."""

    def __init__(self, items, *, title: str = "") -> None:
        self.title = title
        self.items = list(items)
        self.filter = ""
        self.cursor = 0

    @property
    def matches(self) -> list:
        if not self.filter:
            return self.items
        needle = self.filter.lower()
        return [item for item in self.items if needle in item.label.lower()]

    def handle(self, event):
        """Returns the chosen item, CANCEL, or PENDING."""
        visible = self.matches
        if event is Key.ENTER:
            if not visible:
                return PENDING
            return visible[min(self.cursor, len(visible) - 1)]
        if event is Key.ESCAPE:
            return CANCEL
        if event is Key.DOWN:
            self.cursor = min(max(0, len(visible) - 1), self.cursor + 1)
        elif event is Key.UP:
            self.cursor = max(0, self.cursor - 1)
        elif event is Key.BACKSPACE:
            self.filter = self.filter[:-1]
            self.cursor = 0
        elif isinstance(event, str) and event >= " ":
            self.filter += event
            self.cursor = 0
        return PENDING

    def lines(self, height: int) -> list[str]:
        visible = self.matches
        if not visible:
            return ["  (nothing matches)"]
        top = max(0, min(self.cursor - height // 2, len(visible) - height))
        out = []
        for index in range(top, min(len(visible), top + height)):
            item = visible[index]
            marker = "▸" if index == self.cursor else " "
            out.append(f" {marker} {item.label}")
        return out


@dataclass
class Confirm:
    """A yes/no question; destructive answers require a typed word."""

    question: str
    detail: str = ""
    require_word: str = ""
    typed: str = field(default="", init=False)

    def handle(self, event):
        if event is Key.ESCAPE:
            return CANCEL
        if self.require_word:
            if event is Key.ENTER:
                return self.typed == self.require_word
            if event is Key.BACKSPACE:
                self.typed = self.typed[:-1]
            elif isinstance(event, str) and event >= " ":
                self.typed += event
            return PENDING
        if isinstance(event, str) and event.lower() == "y":
            return True
        if isinstance(event, str) and event.lower() == "n" or event is Key.ENTER:
            return False
        return PENDING


class Viewer:
    """A scrollable read-only text panel, for diffs and command output."""

    def __init__(self, lines, *, title: str = "") -> None:
        self.title = title
        self.all_lines = list(lines) or ["(empty)"]
        self.top = 0

    def handle(self, event):
        if event in (Key.ESCAPE, Key.ENTER) or event == "q":
            return CANCEL
        if event is Key.DOWN:
            self.top = min(max(0, len(self.all_lines) - 1), self.top + 1)
        elif event is Key.UP:
            self.top = max(0, self.top - 1)
        elif event is Key.PAGE_DOWN:
            self.top = min(max(0, len(self.all_lines) - 1), self.top + 10)
        elif event is Key.PAGE_UP:
            self.top = max(0, self.top - 10)
        return PENDING

    def lines(self, height: int) -> list:
        return self.all_lines[self.top : self.top + max(1, height)]
