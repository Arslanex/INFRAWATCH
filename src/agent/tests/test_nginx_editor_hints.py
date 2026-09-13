"""Right-hand panel explanations."""
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.modules.nginx.editor import view
from iw_agent.modules.nginx.editor.app import EditorSession
from iw_agent.modules.nginx.editor.document import EditBuffer
from iw_agent.modules.nginx.editor.hints import hint_for_row
from iw_agent.modules.nginx.editor.rows import RowKind

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


def test_proxy_pass_hint_explains_effect(session):
    for row in session.rows:
        if row.node and getattr(row.node, "name", None) == "proxy_pass":
            hint = hint_for_row(row)
            assert "backend" in hint.what.lower()
            assert "traffic" in hint.changes.lower()
            assert "proxy" in hint.add_here.lower()
            return
    pytest.fail("proxy_pass row not found")


def test_add_slot_hint_lists_templates(session):
    add_row = next(row for row in session.rows if row.kind is RowKind.ADD_SLOT)
    hint = hint_for_row(add_row)
    assert hint.title == "add here"
    assert hint.add_here
    assert "proxy" in hint.add_here.lower() or "server block" in hint.add_here.lower()


def test_detail_panel_shows_what_and_changes(session):
    session.handle("j")
    session.handle("j")
    session.handle("j")
    lines = view._detail_lines(session.frame(24))
    body = "\n".join(lines)
    assert "What" in body
    assert "Changes" in body
    assert "Add here" in body
