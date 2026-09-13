"""The actions panel — what used to need four levels of menu."""
import asyncio
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.keys import Key
from iw_agent.cli.tui.screen import Screen
from iw_agent.cli.tui.widgets import Confirm, LineEditor, Picker, Viewer
from iw_agent.modules.nginx.editor import panel, view
from iw_agent.modules.nginx.editor.app import EditorSession
from iw_agent.modules.nginx.editor.document import EditBuffer

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nginx"


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


@pytest.fixture
def session(tmp_path):
    config = tmp_path / "demo.test"
    config.write_text((FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8"))
    return EditorSession(
        buffer=EditBuffer(config.read_text(), str(config)),
        title="demo.test",
    )


def type_text(session, text):
    for char in text:
        session.handle(char)


def dirty(session):
    session.buffer.set_args((1, 4, 0), ["http://127.0.0.1:4000"])
    session.rebuild()


# --- what the panel offers -----------------------------------------------

def test_x_opens_the_panel(session):
    session.handle("x")

    assert isinstance(session.modal.widget, Picker)
    assert session.modal.title == "actions"


def test_the_panel_covers_the_operations_the_old_menus_had(session):
    labels = {action.label for action in panel.ACTIONS}

    assert {"Test config", "Reload nginx", "Enable site", "Disable site",
            "Obtain HTTPS certificate", "Renew certificate"} <= labels


def test_buffer_only_entries_appear_only_when_dirty(session):
    clean = {a.key for a in panel.available(dirty=False)}
    assert "diff" not in clean and "revert" not in clean

    messy = {a.key for a in panel.available(dirty=True)}
    assert "diff" in messy and "revert" in messy


def test_live_site_shows_disable_not_enable():
    keys = {a.key for a in panel.available(dirty=False, site_enabled=True)}
    assert "disable" in keys
    assert "enable" not in keys


def test_off_site_shows_enable_not_disable():
    keys = {a.key for a in panel.available(dirty=False, site_enabled=False)}
    assert "enable" in keys
    assert "disable" not in keys


# --- local actions --------------------------------------------------------

def test_show_changes_opens_a_diff_viewer(session):
    dirty(session)
    session.handle("x")
    type_text(session, "Show")
    session.handle(Key.ENTER)

    assert isinstance(session.modal.widget, Viewer)
    assert any("+" in line for line in session.modal.widget.all_lines)


def test_discard_changes_asks_and_then_reverts(session):
    original = session.buffer.text
    dirty(session)
    session.handle("x")
    type_text(session, "Discard")
    session.handle(Key.ENTER)

    assert isinstance(session.modal.widget, Confirm)
    session.handle("y")

    assert session.buffer.text == original
    assert session.buffer.dirty is False


def test_reload_from_disk_picks_up_an_outside_change(session, tmp_path):
    config = pathlib.Path(session.path)
    config.write_text(config.read_text().replace("3000", "9999"))

    session.handle("x")
    type_text(session, "Reload from disk")
    session.handle(Key.ENTER)

    assert "9999" in session.buffer.text
    assert session.status == "reloaded from disk"


def test_reload_from_disk_when_nothing_changed(session):
    session.handle("x")
    type_text(session, "Reload from disk")
    session.handle(Key.ENTER)

    assert session.status == "already up to date"


# --- pipeline actions -----------------------------------------------------

def test_a_plain_action_is_queued_for_the_loop(session):
    session.handle("x")
    type_text(session, "Test config")
    session.handle(Key.ENTER)

    assert session.modal is None
    assert session.pending_action[0].action_id == "test_config"


def test_a_destructive_action_asks_first(session):
    session.handle("x")
    type_text(session, "Disable")
    session.handle(Key.ENTER)

    assert isinstance(session.modal.widget, Confirm)
    assert session.pending_action is None

    session.handle("n")
    assert session.pending_action is None
    assert session.status == "cancelled"


def test_a_destructive_action_runs_once_confirmed(session):
    session.handle("x")
    type_text(session, "Disable")
    session.handle(Key.ENTER)
    session.handle("y")

    assert session.pending_action[0].action_id == "disable_site"


def test_obtaining_a_certificate_asks_for_an_email(session):
    session.handle("x")
    type_text(session, "Obtain")
    session.handle(Key.ENTER)

    assert isinstance(session.modal.widget, LineEditor)
    type_text(session, "ops@example.com")
    session.handle(Key.ENTER)

    action, extra = session.pending_action
    assert action.action_id == "secure_site"
    assert extra == {"email": "ops@example.com"}


def test_an_empty_email_is_refused(session):
    session.handle("x")
    type_text(session, "Obtain")
    session.handle(Key.ENTER)
    session.handle(Key.ENTER)

    assert session.pending_action is None
    assert "email is required" in session.status


def test_read_only_allows_testing_but_not_changing(tmp_path):
    config = tmp_path / "demo.test"
    config.write_text((FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8"))
    session = EditorSession(
        buffer=EditBuffer(config.read_text(), str(config)),
        title="demo", read_only=True,
    )

    session.handle("x")
    type_text(session, "Test config")
    session.handle(Key.ENTER)
    assert session.pending_action is not None

    session.pending_action = None
    session.handle("x")
    type_text(session, "Reload nginx")
    session.handle(Key.ENTER)
    assert session.pending_action is None
    assert "read-only" in session.status


# --- the action actually runs --------------------------------------------

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
            raise KeyboardInterrupt
        return self.chunks.pop(0)

    def wait_for_escape_tail(self):
        return self.chunks.pop(0) if self.chunks else b""


def test_test_config_runs_through_the_action_pipeline(session, monkeypatch):
    import iw_agent.core.executor_runtime as executor_runtime
    import iw_agent.modules.nginx.executor as nginx_executor
    from iw_agent.core.commands import CommandResult
    from iw_agent.modules.nginx.editor.app import run_editor

    monkeypatch.setattr(executor_runtime, "has_effective_root", lambda: True)
    monkeypatch.setattr(nginx_executor, "is_command_available", lambda _b: True)

    async def nginx_t(argv, timeout, cwd=None):
        return CommandResult(argv=tuple(argv), exit_code=0, stdout="ok", stderr="")

    monkeypatch.setattr(nginx_executor, "run_command", nginx_t)

    session.handle("x")
    type_text(session, "Test config")
    session.handle(Key.ENTER)

    asyncio.run(run_editor(session, terminal=FakeTerminal([b"\x00"])))

    assert "passed" in session.status


# --- frame ----------------------------------------------------------------

def test_the_panel_is_drawn_in_the_side_pane(session):
    session.handle("x")
    screen = Screen(lambda _: None, width=98, height=18)
    view.render(screen, session.frame(18))
    body = "\n".join(screen.snapshot())

    assert "actions" in body
    assert "Test config" in body
