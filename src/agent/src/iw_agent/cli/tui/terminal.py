"""Raw-mode terminal control for the full-screen editor.

Hand-rolled ANSI rather than curses, for three reasons: the rest of the CLI is
already an ANSI string layer (``cli/output.py``) whose formatters stay usable
here; curses writes to stdout before it discovers it has no terminal, which
corrupts piped output; and a plain writer can be faked in tests, while curses
cannot.

Restoring the terminal is treated as the critical path — a crash must never
leave a user without an echo or a cursor, so the restore runs from the context
manager, from ``atexit`` and from SIGTERM/SIGHUP.
"""
from __future__ import annotations

import atexit
import os
import select
import shutil
import signal
import sys
import termios
import tty

ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
CURSOR_HIDE = "\033[?25l"
CURSOR_SHOW = "\033[?25h"
CLEAR_SCREEN = "\033[2J"
CLEAR_LINE = "\033[2K"

# how long to wait for the rest of an escape sequence before calling it a bare
# Escape keypress
ESCAPE_TIMEOUT = 0.05


def supports_fullscreen() -> bool:
    """Whether a full-screen editor can run here at all.

    Checked *before* any escape sequence is emitted: probing by trying and
    failing would already have written to stdout.
    """
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return False
    return os.environ.get("TERM", "") not in {"", "dumb"}


def cursor_to(row: int, column: int) -> str:
    """1-based absolute cursor position."""
    return f"\033[{row};{column}H"


class Terminal:
    """Owns raw mode and the alternate screen for the duration of a session."""

    def __init__(self, *, stream=None, stdin_fd: int | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._fd = stdin_fd if stdin_fd is not None else sys.stdin.fileno()
        self._saved: list | None = None
        self._entered = False
        self._previous_handlers: dict[int, object] = {}

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Terminal:
        self._saved = termios.tcgetattr(self._fd)
        # cbreak, not raw: Ctrl-C still raises KeyboardInterrupt, which the
        # editor treats exactly like 'quit'
        tty.setcbreak(self._fd)
        self.write(ALT_SCREEN_ON + CURSOR_HIDE + CLEAR_SCREEN)
        self._entered = True
        atexit.register(self.restore)
        for signum in (signal.SIGTERM, signal.SIGHUP):
            try:
                self._previous_handlers[signum] = signal.signal(signum, self._on_signal)
            except (ValueError, OSError):
                pass                     # not on the main thread; best effort
        return self

    def __exit__(self, *_exc) -> None:
        self.restore()

    def _on_signal(self, signum, frame) -> None:
        self.restore()
        os._exit(128 + signum)

    def restore(self) -> None:
        if not self._entered:
            return
        self._entered = False
        try:
            self.write(CURSOR_SHOW + ALT_SCREEN_OFF)
        finally:
            if self._saved is not None:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            for signum, handler in self._previous_handlers.items():
                try:
                    signal.signal(signum, handler)
                except (ValueError, OSError):
                    pass
            self._previous_handlers.clear()
            try:
                atexit.unregister(self.restore)
            except Exception:
                pass

    # -- io ----------------------------------------------------------------

    def write(self, text: str) -> None:
        self._stream.write(text)
        self._stream.flush()

    def size(self) -> tuple[int, int]:
        """(columns, rows), with a sane default when the size is unknown."""
        size = shutil.get_terminal_size((80, 24))
        return size.columns, size.lines

    def read(self, timeout: float | None = None) -> bytes:
        """Read whatever is available, blocking until something is or timeout."""
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return b""
        return os.read(self._fd, 4096)

    def wait_for_escape_tail(self) -> bytes:
        """A short second read, to tell a bare Escape from a sequence."""
        return self.read(ESCAPE_TIMEOUT)
