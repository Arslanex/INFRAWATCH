"""Decode a terminal byte stream into key events.

Pure and synchronous on purpose: the editor's input layer is the part most
likely to behave differently across tmux, PuTTY, iTerm and plain xterm, and a
function from bytes to events can be exhaustively unit tested without a
terminal.

Escape sequences are parsed structurally (CSI parameter/intermediate/final
bytes) rather than matched against a fixed table, so an unrecognised sequence
is *swallowed* instead of leaking into the buffer as stray text.
"""
from __future__ import annotations

from enum import Enum

ESC = 0x1B


class Key(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    HOME = "home"
    END = "end"
    PAGE_UP = "page_up"
    PAGE_DOWN = "page_down"
    DELETE = "delete"
    INSERT = "insert"
    ENTER = "enter"
    TAB = "tab"
    SHIFT_TAB = "shift_tab"
    BACKSPACE = "backspace"
    ESCAPE = "escape"
    CTRL_UP = "ctrl_up"
    CTRL_DOWN = "ctrl_down"
    CTRL_LEFT = "ctrl_left"
    CTRL_RIGHT = "ctrl_right"


# (final byte, parameters) -> key
_CSI: dict[tuple[str, str], Key] = {
    ("A", ""): Key.UP,
    ("B", ""): Key.DOWN,
    ("C", ""): Key.RIGHT,
    ("D", ""): Key.LEFT,
    ("H", ""): Key.HOME,
    ("F", ""): Key.END,
    ("Z", ""): Key.SHIFT_TAB,
    ("~", "1"): Key.HOME,
    ("~", "2"): Key.INSERT,
    ("~", "3"): Key.DELETE,
    ("~", "4"): Key.END,
    ("~", "5"): Key.PAGE_UP,
    ("~", "6"): Key.PAGE_DOWN,
    ("~", "7"): Key.HOME,
    ("~", "8"): Key.END,
    ("A", "1;5"): Key.CTRL_UP,
    ("B", "1;5"): Key.CTRL_DOWN,
    ("C", "1;5"): Key.CTRL_RIGHT,
    ("D", "1;5"): Key.CTRL_LEFT,
}

# SS3 sequences, sent when the terminal is in application-cursor mode
_SS3: dict[str, Key] = {
    "A": Key.UP,
    "B": Key.DOWN,
    "C": Key.RIGHT,
    "D": Key.LEFT,
    "H": Key.HOME,
    "F": Key.END,
}

_CONTROL: dict[int, Key] = {
    0x0D: Key.ENTER,
    0x0A: Key.ENTER,
    0x09: Key.TAB,
    0x7F: Key.BACKSPACE,
    0x08: Key.BACKSPACE,
}

Event = "Key | str"


def ctrl(letter: str) -> str:
    """The event a Ctrl-<letter> chord produces, e.g. ``ctrl('c') == '\\x03'``."""
    return chr(ord(letter.lower()) - 0x60)


def decode(data: bytes, *, flush: bool = False) -> tuple[list, bytes]:
    """Split ``data`` into events plus the bytes that are still incomplete.

    ``flush=True`` resolves a trailing lone ESC to :attr:`Key.ESCAPE`; callers
    set it once a short read timeout has passed with no follow-up bytes, which
    is the only way to tell ESC from the start of a sequence.
    """
    events: list = []
    index = 0
    size = len(data)

    while index < size:
        byte = data[index]

        if byte == ESC:
            consumed, event, incomplete = _decode_escape(data, index)
            if incomplete and not flush:
                return events, bytes(data[index:])
            if incomplete:
                events.append(Key.ESCAPE)
                index += 1
                continue
            if event is not None:
                events.append(event)
            index += consumed
            continue

        if byte in _CONTROL:
            events.append(_CONTROL[byte])
            index += 1
            continue

        if byte < 0x20:
            events.append(chr(byte))          # Ctrl-<letter>
            index += 1
            continue

        char, consumed, incomplete = _decode_char(data, index)
        if incomplete and not flush:
            return events, bytes(data[index:])
        if char is not None:
            events.append(char)
        index += consumed

    return events, b""


def _decode_escape(data: bytes, start: int) -> tuple[int, object, bool]:
    """Returns ``(bytes consumed, event or None, incomplete)``."""
    size = len(data)
    if start + 1 >= size:
        return 1, None, True

    second = data[start + 1]

    if second == 0x5B:                                    # CSI: ESC [
        index = start + 2
        params = ""
        while index < size and 0x30 <= data[index] <= 0x3F:
            params += chr(data[index])
            index += 1
        while index < size and 0x20 <= data[index] <= 0x2F:   # intermediates
            index += 1
        if index >= size:
            return 0, None, True
        final = chr(data[index])
        return index + 1 - start, _CSI.get((final, params)), False

    if second == 0x4F:                                    # SS3: ESC O
        if start + 2 >= size:
            return 0, None, True
        return 3, _SS3.get(chr(data[start + 2])), False

    # ESC followed by something else: treat as a bare Escape, keep the rest
    return 1, Key.ESCAPE, False


def _decode_char(data: bytes, start: int) -> tuple[str | None, int, bool]:
    byte = data[start]
    if byte < 0x80:
        length = 1
    elif byte >> 5 == 0b110:
        length = 2
    elif byte >> 4 == 0b1110:
        length = 3
    elif byte >> 3 == 0b11110:
        length = 4
    else:
        return None, 1, False                              # stray continuation

    if start + length > len(data):
        return None, 0, True
    try:
        return data[start : start + length].decode("utf-8"), length, False
    except UnicodeDecodeError:
        return None, 1, False
