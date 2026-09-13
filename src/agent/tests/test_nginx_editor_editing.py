"""Driving the editor the way a person would: arrow to a line, press enter,
type, confirm."""
import asyncio
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.keys import Key, ctrl
from iw_agent.cli.tui.screen import Screen
from iw_agent.cli.tui.widgets import Confirm, LineEditor, Picker
from iw_agent.modules.nginx.confparse import Block
from iw_agent.modules.nginx.editor import view
from iw_agent.modules.nginx.editor.app import EditorSession
from iw_agent.modules.nginx.editor.document import EditBuffer

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
        buffer=EditBuffer(text, "/etc/nginx/sites-available/demo.test"),
        title="demo.test",
    )


def goto(session, needle):
    """Move the cursor onto the first row whose text contains ``needle``."""
    for index, row in enumerate(session.rows):
        if row.selectable and needle in row.text:
            session.cursor = index
            return
    raise AssertionError(f"no selectable row containing {needle!r}")


def type_text(session, text):
    for char in text:
        session.handle(char)


# --- typed forms ----------------------------------------------------------

def test_enter_on_a_known_directive_opens_its_form(session):
    goto(session, "proxy_pass")
    session.handle(Key.ENTER)

    assert isinstance(session.modal.widget, LineEditor)
    assert session.modal.title == "Backend"
    assert session.modal.widget.text == "http://127.0.0.1:3000"


def test_editing_a_value_through_the_form(session):
    goto(session, "proxy_pass")
    session.handle(Key.ENTER)
    for _ in range(4):
        session.handle(Key.BACKSPACE)
    type_text(session, "4000")
    session.handle(Key.ENTER)

    assert session.modal is None
    assert "proxy_pass http://127.0.0.1:4000;" in session.buffer.text
    assert session.buffer.dirty


def test_the_form_rejects_an_invalid_value_and_keeps_the_buffer(session):
    original = session.buffer.text
    goto(session, "proxy_pass")
    session.handle(Key.ENTER)
    for _ in range(40):
        session.handle(Key.BACKSPACE)
    type_text(session, "not a url")
    session.handle(Key.ENTER)

    assert session.buffer.text == original
    assert "http" in session.status.lower() or "unix" in session.status.lower()


def test_escape_cancels_a_form(session):
    original = session.buffer.text
    goto(session, "proxy_pass")
    session.handle(Key.ENTER)
    type_text(session, "junk")
    session.handle(Key.ESCAPE)

    assert session.modal is None
    assert session.buffer.text == original
    assert session.status == "cancelled"


def test_listen_form_lets_you_add_an_address(session):
    """The user's 'add a server IP' case."""
    goto(session, "listen 80;")
    session.handle(Key.ENTER)
    for _ in range(2):
        session.handle(Key.BACKSPACE)
    type_text(session, "127.0.0.1:80")
    session.handle(Key.ENTER)

    assert "listen 127.0.0.1:80;" in session.buffer.text


def test_location_path_is_editable_from_the_block_header(session):
    """The user's 'change the / in a server' case."""
    goto(session, "location / {")
    session.handle(Key.ENTER)
    for _ in range(1):
        session.handle(Key.BACKSPACE)
    type_text(session, "/api")
    session.handle(Key.ENTER)

    assert "location /api {" in session.buffer.text
    assert "proxy_pass http://127.0.0.1:3000;" in session.buffer.text


# --- raw editing ----------------------------------------------------------

def test_e_opens_a_raw_line_editor(session):
    goto(session, "proxy_pass")
    session.handle("e")

    assert session.modal.title == "raw line"
    assert session.modal.widget.text.strip() == "proxy_pass http://127.0.0.1:3000;"


def test_unknown_directives_fall_back_to_raw_editing(session):
    session.buffer.insert_lines((1,), 0, "    fastcgi_buffers 8 16k;")
    session.rebuild()
    goto(session, "fastcgi_buffers")
    session.handle(Key.ENTER)

    assert session.modal.title == "raw line"


def test_a_raw_line_without_a_semicolon_is_refused(session):
    original = session.buffer.text
    goto(session, "proxy_pass")
    session.handle("e")
    for _ in range(60):
        session.handle(Key.BACKSPACE)
    type_text(session, "proxy_pass http://x")
    session.handle(Key.ENTER)

    assert session.buffer.text == original
    assert "';'" in session.status


# --- adding ---------------------------------------------------------------

def test_file_level_add_slot_offers_spacing_not_new_servers(session):
    goto(session, "+ add comment or spacing")
    session.handle(Key.ENTER)

    assert isinstance(session.modal.widget, Picker)
    labels = [item.label for item in session.modal.widget.items]
    assert "comment" in labels
    assert not any("server block" in label for label in labels)


def test_picker_inside_a_location_offers_location_things(session):
    for index, row in enumerate(session.rows):
        if row.text.strip() == "+ add directive" and row.depth == 2:
            session.cursor = index
            break
    session.handle(Key.ENTER)
    labels = [item.label for item in session.modal.widget.items]

    assert "proxy_pass" in labels
    assert "alias" in labels


def _goto_server_add_slot(session):
    for index, row in enumerate(session.rows):
        if row.text.strip() == "+ add location or directive" and row.depth == 1:
            session.cursor = index
            return
    raise AssertionError("server add slot not found")


def test_adding_a_directive_inserts_it_with_the_right_indent(session):
    _goto_server_add_slot(session)
    session.handle(Key.ENTER)
    type_text(session, "client_max")
    session.handle(Key.ENTER)

    line = next(l for l in session.buffer.text.splitlines() if "client_max_body_size" in l)
    assert line == "    client_max_body_size 20m;"


def test_adding_a_location_from_the_server_menu(session):
    goto(session, "+ add location or directive")
    session.handle(Key.ENTER)
    type_text(session, "static")
    session.handle(Key.ENTER)

    assert "try_files $uri $uri/ =404;" in session.buffer.text
    assert session.buffer.text.count("location /") >= 2


def test_the_cursor_lands_on_what_was_just_added(session):
    _goto_server_add_slot(session)
    session.handle(Key.ENTER)
    type_text(session, "client_max")
    session.handle(Key.ENTER)

    assert "client_max_body_size" in session.current.text


def test_security_header_preset_is_available_as_a_template(session):
    """What the deleted security page used to do, as an insert you can see."""
    _goto_server_add_slot(session)
    session.handle(Key.ENTER)
    type_text(session, "security headers — basic")
    session.handle(Key.ENTER)

    assert "X-Frame-Options" in session.buffer.text


# --- deleting -------------------------------------------------------------

def test_delete_asks_first(session):
    original = session.buffer.text
    goto(session, "listen 80;")
    session.handle("d")

    assert isinstance(session.modal.widget, Confirm)
    session.handle("n")
    assert session.buffer.text == original


def test_delete_removes_the_line_once_confirmed(session):
    goto(session, "listen 80;")
    session.handle("d")
    session.handle("y")

    assert "listen 80;" not in session.buffer.text


def test_deleting_a_big_block_needs_a_typed_confirmation(session):
    goto(session, "server {")
    session.handle("d")

    assert session.modal.widget.require_word == "YES"
    session.handle("y")                      # a bare y is not enough
    session.handle(Key.ENTER)
    assert "server {" in session.buffer.text


# --- undo -----------------------------------------------------------------

def test_undo_and_redo_from_the_keyboard(session):
    original = session.buffer.text
    goto(session, "listen 80;")
    session.handle("d")
    session.handle("y")
    assert session.buffer.dirty

    session.handle("u")
    assert session.buffer.text == original
    assert session.status == "undone"

    session.handle(ctrl("r"))
    assert "listen 80;" not in session.buffer.text


def test_undo_with_nothing_to_undo_says_so(session):
    session.handle("u")
    assert session.status == "nothing to undo"


# --- read-only ------------------------------------------------------------

def test_read_only_blocks_every_edit():
    text = (FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8")
    session = EditorSession(buffer=EditBuffer(text, "/x"), title="demo", read_only=True)
    goto(session, "proxy_pass")

    for key in (Key.ENTER, "e", "a", "d"):
        session.handle(key)
        assert session.modal is None
        assert "read-only" in session.status


# --- quitting with unsaved work ------------------------------------------

def test_quitting_dirty_asks_before_discarding(session):
    goto(session, "listen 80;")
    session.handle("d")
    session.handle("y")

    session.handle("q")
    assert session.running is True
    assert isinstance(session.modal.widget, Confirm)

    session.handle("y")
    assert session.running is False


def test_quitting_clean_just_quits(session):
    session.handle("q")
    assert session.running is False


# --- the frame reflects all of it ----------------------------------------

def test_header_shows_the_unsaved_count(session):
    goto(session, "listen 80;")
    session.handle("d")
    session.handle("y")

    screen = Screen(lambda _: None, width=98, height=18)
    view.render(screen, session.frame(18))

    assert "unsaved" in screen.snapshot()[0]


def test_picker_is_drawn_inline_in_the_config_pane(session):
    _goto_server_add_slot(session)
    session.handle(Key.ENTER)
    screen = Screen(lambda _: None, width=98, height=18)
    view.render(screen, session.frame(18))
    body = "\n".join(screen.snapshot())

    assert "filter:" in body
    assert "location" in body.lower()
    assert "What" in body


def test_save_is_requested_only_when_dirty(session):
    session.handle("s")
    assert session.save_requested is False
    assert session.status == "no changes to save"

    goto(session, "listen 80;")
    session.handle("d")
    session.handle("y")
    session.handle("s")
    assert session.save_requested is True


# --- saving, end to end ---------------------------------------------------

class FakeTerminal:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = []

    def write(self, text):
        self.written.append(text)

    def size(self):
        return 96, 20

    def read(self, timeout=None):
        if not self.chunks:
            # a real terminal would block here; the test has said all it
            # wanted to, so end the session the way Ctrl-C would
            raise KeyboardInterrupt
        return self.chunks.pop(0)

    def wait_for_escape_tail(self):
        return self.chunks.pop(0) if self.chunks else b""


@pytest.fixture
def live_site(tmp_path, monkeypatch):
    import iw_agent.core.executor_runtime as executor_runtime
    import iw_agent.modules.nginx.executor as nginx_executor
    from iw_agent.core.commands import CommandResult

    available = tmp_path / "sites-available"
    available.mkdir()
    config = available / "demo.test"
    config.write_text((FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8"))

    monkeypatch.setattr(executor_runtime, "has_effective_root", lambda: True)
    monkeypatch.setattr(nginx_executor, "is_command_available", lambda _b: True)

    async def nginx_t(argv, timeout, cwd=None):
        return CommandResult(argv=tuple(argv), exit_code=0, stdout="", stderr="")

    monkeypatch.setattr(nginx_executor, "run_command", nginx_t)

    from iw_agent.modules.nginx.editor.app import load_session

    session = load_session(
        str(config),
        title="demo.test",
        action_params={
            "sites_available_dir": str(available),
            "audit_log_path": str(tmp_path / "audit.log"),
        },
    )
    session.action_params.pop("audit_log_path")
    return session, config, tmp_path


def test_pressing_s_writes_the_file(live_site):
    from iw_agent.modules.nginx.editor.app import run_editor

    session, config, _ = live_site
    goto(session, "proxy_pass")
    session.handle(Key.ENTER)
    for _ in range(4):
        session.handle(Key.BACKSPACE)
    type_text(session, "4000")
    session.handle(Key.ENTER)
    assert session.buffer.dirty

    asyncio.run(run_editor(session, terminal=FakeTerminal([b"s"])))

    assert "proxy_pass http://127.0.0.1:4000;" in config.read_text()
    assert "nginx -t passed" in session.status
    assert session.buffer.dirty is False        # baseline moved to what was written


def test_a_rejected_config_is_rolled_back_and_reported(live_site, monkeypatch):
    import iw_agent.modules.nginx.executor as nginx_executor
    from iw_agent.core.commands import CommandResult
    from iw_agent.modules.nginx.editor.app import run_editor

    session, config, _ = live_site
    original = config.read_text()
    answers = [
        CommandResult(argv=("nginx", "-t"), exit_code=0, stdout="", stderr=""),
        CommandResult(argv=("nginx", "-t"), exit_code=1, stdout="", stderr="nginx: [emerg] nope"),
    ]

    async def nginx_t(argv, timeout, cwd=None):
        return answers.pop(0) if answers else answers[-1]

    monkeypatch.setattr(nginx_executor, "run_command", nginx_t)

    goto(session, "proxy_pass")
    session.handle(Key.ENTER)
    for _ in range(4):
        session.handle(Key.BACKSPACE)
    type_text(session, "4000")
    session.handle(Key.ENTER)

    asyncio.run(run_editor(session, terminal=FakeTerminal([b"s"])))

    assert config.read_text() == original       # rolled back
    assert "rolled back" in session.status
    assert session.buffer.dirty is True         # the edit is still in the buffer
