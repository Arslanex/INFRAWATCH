"""Flatten a config tree into the rows shown in the left pane.

The pane has to look like the file, so rows map one-to-one onto source lines.
Only the first line of a node is selectable, which is what makes the arrow
keys step between directives and blocks rather than through wrapped text.

Every block also gets a synthetic "+ add" row as its last child, and the file
gets one at the end. That is the "add new is available everywhere"
requirement: a real row you arrow onto, not a shortcut you have to know.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from iw_agent.modules.nginx.confparse import (
    Blank,
    Block,
    Comment,
    Directive,
    Document,
    Node,
    Raw,
)


class RowKind(Enum):
    BLOCK_OPEN = "block_open"
    BLOCK_CLOSE = "block_close"
    BLOCK_FOLDED = "block_folded"
    DIRECTIVE = "directive"
    COMMENT = "comment"
    BLANK = "blank"
    RAW = "raw"
    ADD_SLOT = "add_slot"


@dataclass
class Row:
    kind: RowKind
    depth: int
    text: str
    node: Node | None = None
    line_no: int | None = None
    selectable: bool = True
    is_anchor: bool = True
    insert_parent: Node | None = None
    insert_index: int | None = None
    # index path from the document root; survives the re-parse that follows
    # every edit, which node identity does not
    path: tuple = ()


def line_count(node: Node) -> int:
    return len(node.render())


def _text_of(node: Node, index: int) -> str:
    rendered = node.render()
    line = rendered[index] if index < len(rendered) else ""
    return line.rstrip("\r\n")


def _add_label(parent: Node) -> str:
    if isinstance(parent, Document):
        return "+ add comment or spacing"
    name = getattr(parent, "name", "") or "block"
    if name == "server":
        return "+ add location or directive"
    if name == "location":
        return "+ add directive"
    return "+ add directive"


def build_rows(document: Document, folded: frozenset[int] = frozenset()) -> list[Row]:
    rows: list[Row] = []
    counter = _LineCounter()
    _emit_children(document, rows, counter, folded, depth=0, path=())
    rows.append(
        Row(
            kind=RowKind.ADD_SLOT,
            depth=0,
            text=_add_label(document),
            insert_parent=document,
            insert_index=len(document.children),
            line_no=None,
            path=(),
        )
    )
    return rows


class _LineCounter:
    def __init__(self) -> None:
        self.value = 1

    def take(self, count: int = 1) -> int:
        first = self.value
        self.value += count
        return first


def _emit_children(
    parent: Node,
    rows: list[Row],
    counter: _LineCounter,
    folded: frozenset[int],
    *,
    depth: int,
    path: tuple,
) -> None:
    children = getattr(parent, "children", [])
    for index, child in enumerate(children):
        _emit_node(
            child, rows, counter, folded,
            depth=depth, index=index, path=path + (index,),
        )

    if isinstance(parent, Block):
        rows.append(
            Row(
                kind=RowKind.ADD_SLOT,
                depth=depth,
                text=_add_label(parent),
                insert_parent=parent,
                insert_index=len(children),
                line_no=None,
                path=path,
            )
        )


def _emit_node(
    node: Node,
    rows: list[Row],
    counter: _LineCounter,
    folded: frozenset[int],
    *,
    depth: int,
    index: int,
    path: tuple,
) -> None:
    if isinstance(node, Block):
        if id(node) in folded:
            total = line_count(node)
            header = _text_of(node, 0).rstrip()
            summary = f"{header} … }}   {total} lines"
            rows.append(
                Row(
                    kind=RowKind.BLOCK_FOLDED,
                    depth=depth,
                    text=summary,
                    node=node,
                    line_no=counter.take(total),
                    path=path,
                )
            )
            return

        header_lines = len(node.header_raw) if node.header_raw else 1
        _emit_lines(node, rows, counter, RowKind.BLOCK_OPEN, depth, header_lines, 0, path)
        _emit_children(node, rows, counter, folded, depth=depth + 1, path=path)
        if node.close_raw:
            rows.append(
                Row(
                    kind=RowKind.BLOCK_CLOSE,
                    depth=depth,
                    text=node.close_raw[0].rstrip("\r\n"),
                    node=node,
                    line_no=counter.take(),
                    selectable=False,
                    path=path,
                )
            )
        return

    kind = {
        Directive: RowKind.DIRECTIVE,
        Comment: RowKind.COMMENT,
        Blank: RowKind.BLANK,
        Raw: RowKind.RAW,
    }.get(type(node), RowKind.RAW)
    _emit_lines(node, rows, counter, kind, depth, line_count(node), 0, path)


def _emit_lines(
    node: Node,
    rows: list[Row],
    counter: _LineCounter,
    kind: RowKind,
    depth: int,
    count: int,
    offset: int,
    path: tuple,
) -> None:
    for step in range(count):
        rows.append(
            Row(
                kind=kind,
                depth=depth,
                text=_text_of(node, offset + step),
                node=node,
                line_no=counter.take(),
                # only the first line of a node is a navigation stop
                selectable=(step == 0 and kind is not RowKind.BLANK),
                is_anchor=(step == 0),
                path=path,
            )
        )


# -- cursor helpers --------------------------------------------------------


def selectable_indexes(rows: list[Row]) -> list[int]:
    return [index for index, row in enumerate(rows) if row.selectable]


def first_selectable(rows: list[Row]) -> int:
    indexes = selectable_indexes(rows)
    return indexes[0] if indexes else 0


def move(rows: list[Row], current: int, delta: int) -> int:
    """Step to the next selectable row, stopping at the ends."""
    indexes = selectable_indexes(rows)
    if not indexes:
        return current
    if current in indexes:
        position = indexes.index(current)
    else:
        position = min(range(len(indexes)), key=lambda i: abs(indexes[i] - current))
    return indexes[max(0, min(len(indexes) - 1, position + delta))]


def reanchor(rows: list[Row], node: Node | None, fallback: int) -> int:
    """Keep the cursor on the same node after the tree is rebuilt."""
    if node is not None:
        for index, row in enumerate(rows):
            if row.node is node and row.selectable:
                return index
    indexes = selectable_indexes(rows)
    if not indexes:
        return 0
    return min(indexes, key=lambda i: abs(i - fallback))


def reanchor_by_path(rows: list[Row], path, fallback: int) -> int:
    """Put the cursor back on a node identified by its tree path.

    Used after an edit, because re-parsing replaces every node object and
    identity no longer means anything.
    """
    if path is not None:
        for index, row in enumerate(rows):
            if row.selectable and row.path == tuple(path) and row.kind is not RowKind.ADD_SLOT:
                return index
        # the node is gone (deleted, or merged away) — aim at its neighbour
        for index, row in enumerate(rows):
            if row.selectable and row.path[: len(path)] == tuple(path)[: len(row.path)]:
                return index
    indexes = selectable_indexes(rows)
    if not indexes:
        return 0
    return min(indexes, key=lambda i: abs(i - fallback))
