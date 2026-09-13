"""Rows are what the user actually sees and arrows through."""
import pathlib

import pytest

from iw_agent.modules.nginx.confparse import Block, Directive, parse
from iw_agent.modules.nginx.editor.rows import (
    Row,
    RowKind,
    build_rows,
    first_selectable,
    move,
    reanchor,
    selectable_indexes,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nginx"


def _doc(name):
    return parse((FIXTURES / name).read_bytes().decode("utf-8"))


def _rows(name, folded=frozenset()):
    return build_rows(_doc(name), folded)


# --- the pane mirrors the file -------------------------------------------

def test_every_source_line_has_a_row():
    text = (FIXTURES / "simple_proxy.conf").read_bytes().decode("utf-8")
    rows = build_rows(parse(text))
    real = [r for r in rows if r.line_no is not None]

    assert [r.line_no for r in real] == list(range(1, len(text.splitlines()) + 1))
    assert [r.text for r in real] == text.splitlines()


def test_depth_follows_nesting():
    rows = _rows("nested_location.conf")
    by_text = {r.text.strip(): r.depth for r in rows if r.node}

    assert by_text["server {"] == 0
    assert by_text["location /api {"] == 1
    assert by_text["location /api/health {"] == 2


# --- "add new" is available everywhere -----------------------------------

def test_each_block_ends_with_an_add_slot():
    rows = _rows("nested_location.conf")
    slots = [r for r in rows if r.kind is RowKind.ADD_SLOT]

    parents = [getattr(r.insert_parent, "name", "file") for r in slots]
    assert parents == ["location", "location", "server", "file"]


def test_the_file_ends_with_an_add_server_slot():
    rows = _rows("simple_proxy.conf")

    assert rows[-1].kind is RowKind.ADD_SLOT
    assert rows[-1].text == "+ add server block"
    assert rows[-1].insert_index == len(_doc("simple_proxy.conf").children)


def test_add_slots_are_selectable():
    rows = _rows("simple_proxy.conf")
    slots = [r for r in rows if r.kind is RowKind.ADD_SLOT]

    assert slots and all(r.selectable for r in slots)


# --- what the arrows stop on ---------------------------------------------

def test_blank_lines_are_shown_but_skipped():
    rows = _rows("simple_proxy.conf")
    blanks = [r for r in rows if r.kind is RowKind.BLANK]

    assert blanks
    assert not any(r.selectable for r in blanks)


def test_closing_braces_are_shown_but_skipped():
    rows = _rows("simple_proxy.conf")
    closes = [r for r in rows if r.kind is RowKind.BLOCK_CLOSE]

    assert closes
    assert not any(r.selectable for r in closes)


def test_move_walks_selectable_rows_only():
    rows = _rows("simple_proxy.conf")
    cursor = first_selectable(rows)
    seen = [cursor]
    for _ in range(6):
        cursor = move(rows, cursor, 1)
        seen.append(cursor)

    assert all(rows[i].selectable for i in seen)
    assert seen == sorted(seen)


def test_move_stops_at_the_ends():
    rows = _rows("simple_proxy.conf")
    indexes = selectable_indexes(rows)

    assert move(rows, indexes[0], -5) == indexes[0]
    assert move(rows, indexes[-1], 5) == indexes[-1]


# --- folding --------------------------------------------------------------

def test_folding_a_block_collapses_it_to_one_row():
    doc = _doc("simple_proxy.conf")
    location = next(
        n for n in doc.walk() if isinstance(n, Block) and n.name == "location"
    )
    folded = build_rows(doc, frozenset({id(location)}))

    assert len(folded) < len(build_rows(doc))
    marker = next(r for r in folded if r.kind is RowKind.BLOCK_FOLDED)
    assert marker.node is location
    assert "lines" in marker.text


def test_folding_keeps_later_line_numbers_correct():
    doc = _doc("simple_proxy.conf")
    location = next(
        n for n in doc.walk() if isinstance(n, Block) and n.name == "location"
    )
    folded = build_rows(doc, frozenset({id(location)}))
    numbered = [r.line_no for r in folded if r.line_no is not None]

    # the closing brace of the server block keeps its real number
    assert numbered[-1] == 12


# --- cursor survives a rebuild -------------------------------------------

def test_reanchor_follows_the_node():
    doc = _doc("simple_proxy.conf")
    rows = build_rows(doc)
    proxy = next(
        n for n in doc.walk() if isinstance(n, Directive) and n.name == "proxy_pass"
    )
    index = next(i for i, r in enumerate(rows) if r.node is proxy and r.selectable)

    location = next(n for n in doc.walk() if isinstance(n, Block) and n.name == "location")
    rebuilt = build_rows(doc, frozenset())
    assert reanchor(rebuilt, proxy, 0) == index


def test_reanchor_falls_back_to_the_nearest_row():
    rows = _rows("simple_proxy.conf")

    assert reanchor(rows, None, 5) in selectable_indexes(rows)


def test_empty_document_still_offers_an_add_slot():
    rows = build_rows(parse(""))

    assert len(rows) == 1
    assert rows[0].kind is RowKind.ADD_SLOT
