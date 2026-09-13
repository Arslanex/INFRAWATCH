"""Session navigation and the guards around entering the editor at all."""
import asyncio
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.keys import Key, ctrl
from iw_agent.cli.tui.screen import Screen
from iw_agent.modules.nginx.confparse import Block
from iw_agent.modules.nginx.editor import view
from iw_agent.modules.nginx.editor.document import EditBuffer
from iw_agent.modules.nginx.editor.app import (
    EditorSession,
    EditorUnavailable,
    load_session,
    run_editor,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nginx"


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


@pytest.fixture
def session():
    text = (FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8")
    return EditorSession(
        buffer=EditBuffer(text, "/etc/nginx/sites-available/demo"),
        title="demo.test",
    )


def _text(session):
    return session.current.text.strip()


# --- navigation -----------------------------------------------------------

def test_starts_on_the_first_selectable_row(session):
    assert _text(session) == "# Created by InfraWatch"


def test_down_and_up(session):
    session.handle(Key.DOWN)
    assert _text(session) == "server {"
    session.handle(Key.UP)
    assert _text(session) == "# Created by InfraWatch"


def test_vim_keys_work_too(session):
    session.handle("j")
    assert _text(session) == "server {"
    session.handle("k")
    assert _text(session) == "# Created by InfraWatch"


def test_end_jumps_to_the_add_slot(session):
    session.handle(Key.END)
    assert _text(session) == "+ add server block"


def test_home_returns_to_the_top(session):
    session.handle(Key.END)
    session.handle(Key.HOME)
    assert _text(session) == "# Created by InfraWatch"


# --- folding --------------------------------------------------------------

def test_left_folds_the_block_under_the_cursor(session):
    session.handle(Key.DOWN)                       # server {
    assert isinstance(session.current.node, Block)

    session.handle(Key.LEFT)
    assert len(session.folded) == 1
    assert "lines" in _text(session)                # collapsed to one row


def test_right_unfolds_it_again(session):
    session.handle(Key.DOWN)
    session.handle(Key.LEFT)
    session.handle(Key.RIGHT)

    assert session.folded == set()
    assert _text(session) == "server {"


def test_left_on_a_directive_jumps_to_the_parent_block(session):
    for _ in range(3):
        session.handle(Key.DOWN)                   # into the server block
    assert _text(session) == "listen [::]:80;"

    session.handle(Key.LEFT)
    assert _text(session) == "server {"


def test_right_on_an_open_block_steps_inside(session):
    session.handle(Key.DOWN)                       # server {
    session.handle(Key.RIGHT)

    assert _text(session) == "listen 80;"


# --- quitting -------------------------------------------------------------

@pytest.mark.parametrize("key", ["q", ctrl("c")])
def test_quit_keys_stop_the_session(session, key):
    session.handle(key)
    assert session.running is False


def test_enter_opens_a_typed_form(session):
    for _ in range(2):
        session.handle(Key.DOWN)                   # listen 80;
    session.handle(Key.ENTER)

    assert session.modal is not None
    assert session.modal.title == "Listen"


# --- frame ----------------------------------------------------------------

def test_frame_keeps_the_cursor_in_view(session):
    session.handle(Key.END)
    frame = session.frame(height=10)

    assert frame.top <= frame.cursor < frame.top + view.body_height(10)


def test_rendered_frame_shows_the_file_and_the_add_slots(session):
    screen = Screen(lambda _: None, width=96, height=20)
    view.render(screen, session.frame(20))
    body = "\n".join(screen.snapshot())

    assert "server {" in body
    assert "proxy_pass http://127.0.0.1:3000;" in body
    assert "+ add directive" in body
    assert "+ add server block" in body
    assert "demo.test" in body


def test_tiny_terminal_is_refused_politely():
    text = (FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8")
    session = EditorSession(buffer=EditBuffer(text, "/x"), title="demo")
    screen = Screen(lambda _: None, width=30, height=5)
    view.render(screen, session.frame(5))

    assert "too small" in screen.snapshot()[0]


def test_narrow_terminal_drops_the_right_pane(session):
    screen = Screen(lambda _: None, width=60, height=20)
    view.render(screen, session.frame(20))

    assert "│" not in "\n".join(screen.snapshot())


# --- entering the editor --------------------------------------------------

def test_editor_refuses_a_non_interactive_terminal(session, monkeypatch):
    import iw_agent.modules.nginx.editor.app as app

    monkeypatch.setattr(app, "supports_fullscreen", lambda: False)
    with pytest.raises(EditorUnavailable, match="interactive terminal"):
        asyncio.run(run_editor(session))


def test_load_session_reads_the_file(tmp_path):
    path = tmp_path / "demo.test"
    path.write_text((FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8"))

    session = load_session(str(path), title="demo.test")

    assert session.title == "demo.test"
    assert session.path == str(path)
    assert any(r.text.strip() == "server {" for r in session.rows)


# --- the loop, end to end -------------------------------------------------

class FakeTerminal:
    """Feeds canned keystrokes and records what would reach the terminal."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = []

    def write(self, text):
        self.written.append(text)

    def size(self):
        return 96, 20

    def read(self, timeout=None):
        return self.chunks.pop(0) if self.chunks else b"q"

    def wait_for_escape_tail(self):
        # a real terminal returns whatever arrived within the timeout
        return self.chunks.pop(0) if self.chunks else b""


def test_the_key_loop_navigates_and_exits(session):
    terminal = FakeTerminal([b"\x1b[B", b"\x1b[B", b"q"])

    asyncio.run(run_editor(session, terminal=terminal))

    assert session.running is False
    assert _text(session) == "listen 80;"          # two rows down
    assert terminal.written                         # something was painted


def test_the_loop_reassembles_a_split_escape_sequence(session):
    """Arrow keys can arrive in pieces; the loop must not give up on them."""
    terminal = FakeTerminal([b"\x1b", b"[", b"B", b"q"])

    asyncio.run(run_editor(session, terminal=terminal))

    assert _text(session) == "server {"


def test_a_lone_escape_is_not_mistaken_for_a_sequence(session):
    terminal = FakeTerminal([b"\x1b", b"", b"q"])

    asyncio.run(run_editor(session, terminal=terminal))

    assert session.running is False
    assert _text(session) == "# Created by InfraWatch"     # nothing moved


def test_search_jumps_to_matching_rows(session):
    session._apply_search("proxy_pass")
    assert session.search_label == "proxy_pass"
    assert "proxy_pass" in _text(session)


def test_help_opens_an_overlay(session):
    session._open_help()
    assert session.modal is not None
    assert session.modal.title == "help"


def test_dry_run_allows_save_without_read_only_guard(session):
    session.dry_run = True
    session.read_only = True
    for row in session.rows:
        if getattr(row.node, "name", None) == "listen":
            session.buffer.set_args(row.path, ["8080"])
            break
    assert session.buffer.dirty
    session._save()
    assert session.save_requested is True


def test_the_loop_repaints_only_on_change(session):
    terminal = FakeTerminal([b"\x1b[B", b"q"])
    asyncio.run(run_editor(session, terminal=terminal))
    first = len(terminal.written)

    session.running = True
    quiet = FakeTerminal([b"\x00", b"q"])          # a key that changes nothing
    asyncio.run(run_editor(session, terminal=quiet))

    assert len(quiet.written) < first
