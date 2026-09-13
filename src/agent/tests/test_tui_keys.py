"""Key decoding is where terminals differ most, so it is pinned exhaustively."""
import pytest

from iw_agent.cli.tui.keys import Key, ctrl, decode


def only(data, *, flush=True):
    events, rest = decode(data, flush=flush)
    assert rest == b""
    return events


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (b"\x1b[A", Key.UP),
        (b"\x1b[B", Key.DOWN),
        (b"\x1b[C", Key.RIGHT),
        (b"\x1b[D", Key.LEFT),
        # application cursor mode, which tmux and some terminals use
        (b"\x1bOA", Key.UP),
        (b"\x1bOB", Key.DOWN),
        (b"\x1bOC", Key.RIGHT),
        (b"\x1bOD", Key.LEFT),
        (b"\x1b[H", Key.HOME),
        (b"\x1b[F", Key.END),
        (b"\x1b[1~", Key.HOME),
        (b"\x1b[4~", Key.END),
        (b"\x1b[7~", Key.HOME),
        (b"\x1b[8~", Key.END),
        (b"\x1b[5~", Key.PAGE_UP),
        (b"\x1b[6~", Key.PAGE_DOWN),
        (b"\x1b[3~", Key.DELETE),
        (b"\x1b[2~", Key.INSERT),
        (b"\x1b[Z", Key.SHIFT_TAB),
        (b"\x1b[1;5A", Key.CTRL_UP),
        (b"\x1b[1;5D", Key.CTRL_LEFT),
        (b"\r", Key.ENTER),
        (b"\n", Key.ENTER),
        (b"\t", Key.TAB),
        (b"\x7f", Key.BACKSPACE),
        (b"\x08", Key.BACKSPACE),
    ],
)
def test_known_sequences(data, key):
    assert only(data) == [key]


def test_printable_characters():
    assert only(b"abc") == ["a", "b", "c"]


def test_utf8_characters():
    assert only("şğü".encode()) == ["ş", "ğ", "ü"]


def test_control_chords_arrive_as_raw_characters():
    assert only(b"\x03") == [ctrl("c")]
    assert only(b"\x12") == [ctrl("r")]


def test_unknown_escape_sequences_are_swallowed_not_typed():
    """A sequence we do not handle must never land in the buffer as text."""
    assert only(b"\x1b[?2004h") == []
    assert only(b"\x1b[200~") == []


def test_unknown_sequence_does_not_eat_what_follows():
    assert only(b"\x1b[?99zx") == ["x"]


def test_partial_sequence_is_held_back():
    events, rest = decode(b"\x1b[")
    assert events == []
    assert rest == b"\x1b["

    events, rest = decode(rest + b"A")
    assert events == [Key.UP]
    assert rest == b""


def test_partial_utf8_is_held_back():
    data = "ş".encode()
    events, rest = decode(data[:1])
    assert events == []
    assert rest == data[:1]
    assert decode(rest + data[1:])[0] == ["ş"]


def test_lone_escape_needs_a_flush():
    """Without flush an ESC could still be the start of a sequence."""
    assert decode(b"\x1b") == ([], b"\x1b")
    assert only(b"\x1b") == [Key.ESCAPE]


def test_mixed_stream():
    assert only(b"j\x1b[Bk\r") == ["j", Key.DOWN, "k", Key.ENTER]


def test_ctrl_helper():
    assert ctrl("c") == "\x03"
    assert ctrl("A") == "\x01"
