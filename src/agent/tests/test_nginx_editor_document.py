"""The edit buffer: every change must be reversible and never leave the
buffer in a state the parser cannot vouch for."""
import pathlib

import pytest

from iw_agent.modules.nginx.confparse import Block, Directive, render
from iw_agent.modules.nginx.editor.document import (
    EditBuffer,
    EditRejected,
    node_at,
    path_of,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nginx"


@pytest.fixture
def buffer():
    text = (FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8")
    return EditBuffer(text, "/etc/nginx/sites-available/demo.test")


PROXY_PATH = (1, 4, 0)      # server > location / > proxy_pass


# --- paths ----------------------------------------------------------------

def test_path_of_and_node_at_agree(buffer):
    node = node_at(buffer.document, PROXY_PATH)

    assert isinstance(node, Directive)
    assert node.name == "proxy_pass"
    assert path_of(node) == PROXY_PATH


def test_node_at_rejects_a_path_that_is_gone(buffer):
    with pytest.raises(EditRejected):
        node_at(buffer.document, (99,))


# --- typed edits ----------------------------------------------------------

def test_set_args_changes_one_line_only(buffer):
    before = buffer.text.splitlines()
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])
    after = buffer.text.splitlines()

    assert len(before) == len(after)
    changed = [i for i, (b, a) in enumerate(zip(before, after)) if b != a]
    assert len(changed) == 1
    assert after[changed[0]].strip() == "proxy_pass http://127.0.0.1:4000;"


def test_set_args_keeps_the_original_indentation(buffer):
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])

    line = next(l for l in buffer.text.splitlines() if "proxy_pass" in l)
    assert line.startswith("        ")


def test_set_args_on_a_block_header(buffer):
    location = next(
        n for n in buffer.document.walk() if isinstance(n, Block) and n.name == "location"
    )
    buffer.set_args(path_of(location), ["/api"])

    assert "location /api {" in buffer.text
    assert "proxy_pass http://127.0.0.1:3000;" in buffer.text     # children kept


def test_set_args_refuses_a_line_that_is_not_structured(buffer):
    comment_path = (0,)
    with pytest.raises(EditRejected, match="no structured value"):
        buffer.set_args(comment_path, ["x"])


# --- raw edits ------------------------------------------------------------

def test_replace_lines_accepts_a_valid_line(buffer):
    buffer.replace_lines((1, 0), "    listen 8080;")

    assert "listen 8080;" in buffer.text
    assert "listen 80;" not in buffer.text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("listen 80", "no ';'"),                 # would silently merge with the next line
        ("location / {", "unclosed"),
        ("}", "unexpected"),
        ("   ", "nothing to insert"),
    ],
)
def test_replace_lines_refuses_a_fragment_that_cannot_stand_alone(buffer, text, expected):
    before = buffer.text
    with pytest.raises(EditRejected, match=expected):
        buffer.replace_lines((1, 0), text)

    assert buffer.text == before                 # buffer untouched by a failed edit


# --- inserting ------------------------------------------------------------

def test_insert_lines_returns_the_new_path(buffer):
    path = buffer.insert_lines((1,), 3, "    client_max_body_size 20m;")

    node = node_at(buffer.document, path)
    assert isinstance(node, Directive)
    assert node.name == "client_max_body_size"


def test_insert_lines_accepts_a_whole_block(buffer):
    buffer.insert_lines((1,), 3, "    location /api {\n        proxy_pass http://127.0.0.1:9000;\n    }")

    location_paths = [
        n for n in buffer.document.walk() if isinstance(n, Block) and n.name == "location"
    ]
    assert len(location_paths) == 2
    assert "location /api {" in buffer.text


def test_insert_clamps_an_out_of_range_index(buffer):
    path = buffer.insert_lines((1,), 999, "    client_max_body_size 20m;")

    assert node_at(buffer.document, path).name == "client_max_body_size"


# --- deleting -------------------------------------------------------------

def test_delete_removes_a_directive(buffer):
    buffer.delete((1, 0))

    assert "listen 80;" not in buffer.text
    assert "listen [::]:80;" in buffer.text


def test_delete_removes_a_whole_block_with_its_children(buffer):
    buffer.delete((1, 4))

    assert "location /" not in buffer.text
    assert "proxy_pass" not in buffer.text
    assert "server_name demo.test www.demo.test;" in buffer.text


# --- undo -----------------------------------------------------------------

def test_undo_restores_the_exact_original_bytes(buffer):
    original = buffer.text
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])
    buffer.insert_lines((1,), 0, "    client_max_body_size 20m;")
    buffer.delete((1, 0))

    while buffer.can_undo():
        buffer.undo()

    assert buffer.text == original
    assert buffer.dirty is False


def test_redo_replays(buffer):
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])
    edited = buffer.text
    buffer.undo()
    assert buffer.text != edited

    buffer.redo()
    assert buffer.text == edited


def test_a_new_edit_clears_the_redo_stack(buffer):
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])
    buffer.undo()
    assert buffer.can_redo()

    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:5000"])
    assert not buffer.can_redo()


def test_a_rejected_edit_does_not_land_on_the_undo_stack(buffer):
    with pytest.raises(EditRejected):
        buffer.replace_lines((1, 0), "listen 80")

    assert not buffer.can_undo()


# --- dirty tracking -------------------------------------------------------

def test_clean_at_the_start(buffer):
    assert buffer.dirty is False
    assert buffer.changed_lines() == 0


def test_dirty_after_an_edit(buffer):
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])

    assert buffer.dirty is True
    assert buffer.changed_lines() == 2          # one line out, one line in
    assert "127.0.0.1:4000" in buffer.diff()


def test_mark_saved_resets_the_baseline(buffer):
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])
    buffer.mark_saved()

    assert buffer.dirty is False
    assert buffer.base_sha256 == EditBuffer(buffer.text, "/x").base_sha256


# --- indentation ----------------------------------------------------------

def test_indent_unit_is_sniffed_from_the_file(buffer):
    assert buffer.indent_unit() == "    "


def test_tab_indented_files_stay_tab_indented():
    text = (FIXTURES / "tabs_indent.conf").read_bytes().decode("utf-8")
    tabbed = EditBuffer(text, "/x")

    assert tabbed.indent_unit() == "\t"
    assert tabbed.indent_for((0,)) == "\t"


def test_indent_for_nests_one_level_deeper(buffer):
    assert buffer.indent_for(()) == ""
    assert buffer.indent_for((1,)) == "    "
    assert buffer.indent_for((1, 4)) == "        "


# --- the buffer always round-trips ---------------------------------------

def test_buffer_text_always_reparses_cleanly(buffer):
    buffer.set_args(PROXY_PATH, ["http://127.0.0.1:4000"])
    buffer.insert_lines((1,), 0, "    client_max_body_size 20m;")

    from iw_agent.modules.nginx.confparse import parse

    assert render(parse(buffer.text)) == buffer.text
