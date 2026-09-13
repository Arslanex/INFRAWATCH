"""The edit buffer: a config tree plus undo, dirty tracking and edit ops.

Every edit renders the tree to text and re-parses it. That costs about a
millisecond on a real site config and buys two things worth far more: the tree
can never drift out of step with the text that will be written, and undo is a
plain text snapshot rather than a stack of inverse operations that has to be
correct for every op.

Because re-parsing builds new node objects, edits address nodes by their index
path from the document root rather than by identity.
"""
from __future__ import annotations

from iw_agent.modules.nginx.confparse import (
    Block,
    Directive,
    Document,
    NginxParseError,
    Node,
    Raw,
    check,
    parse,
    render,
)
from iw_agent.modules.nginx.safe_write import diff_stat, sha256_text, unified_diff

UNDO_LIMIT = 200


class EditRejected(Exception):
    """The edit would produce a config the parser cannot vouch for."""


def path_of(node: Node) -> tuple:
    """Index path from the document root, e.g. ``(0, 3, 1)``."""
    path: list[int] = []
    current = node
    while current is not None:
        parent = current.parent
        if parent is None:
            break
        children = getattr(parent, "children", [])
        for index, child in enumerate(children):
            if child is current:
                path.append(index)
                break
        current = parent
    return tuple(reversed(path))


def node_at(document: Document, path) -> Node:
    node: Node = document
    for index in path:
        children = getattr(node, "children", [])
        if index >= len(children):
            raise EditRejected(f"no node at path {path}")
        node = children[index]
    return node


class EditBuffer:
    def __init__(self, text: str, path: str) -> None:
        self.path = path
        self.base_text = text
        self.base_sha256 = sha256_text(text)
        self.document = parse(text, path=path)
        self._undo: list[str] = []
        self._redo: list[str] = []

    # -- state -------------------------------------------------------------

    @property
    def text(self) -> str:
        return render(self.document)

    @property
    def dirty(self) -> bool:
        return self.text != self.base_text

    @property
    def newline(self) -> str:
        return self.document.newline

    def changed_lines(self) -> int:
        added, removed = diff_stat(self.base_text, self.text)
        return added + removed

    def diff(self) -> str:
        return unified_diff(self.base_text, self.text, self.path)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def mark_saved(self) -> None:
        self.base_text = self.text
        self.base_sha256 = sha256_text(self.base_text)

    # -- commit ------------------------------------------------------------

    def _commit(self, new_text: str, previous_text: str) -> None:
        """Swap in the edited text, recording what it replaced.

        ``previous_text`` is passed explicitly because edits mutate the tree
        in place, so by the time this runs ``self.text`` already reflects the
        change and cannot serve as the undo snapshot.
        """
        try:
            check(new_text)
        except NginxParseError as exc:
            raise EditRejected(str(exc)) from exc

        self._undo.append(previous_text)
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.document = parse(new_text, path=self.path)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.text)
        self.document = parse(self._undo.pop(), path=self.path)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.text)
        self.document = parse(self._redo.pop(), path=self.path)
        return True

    # -- edits -------------------------------------------------------------

    def set_args(self, path, args: list[str]) -> None:
        """Replace the value of a directive, or the header args of a block."""
        before = self.text
        node = node_at(self.document, path)
        if not isinstance(node, (Directive, Block)):
            raise EditRejected("this line has no structured value to edit")
        previous = list(node.args)
        node.args = list(args)
        node.dirty = True
        try:
            self._commit(render(self.document), before)
        except EditRejected:
            node.args = previous
            node.dirty = False
            self.document = parse(before, path=self.path)
            raise

    def replace_lines(self, path, text: str) -> None:
        """Swap a node for whatever the user typed, validated by re-parsing."""
        before = self.text
        parent_path, index = path[:-1], path[-1]
        parent = node_at(self.document, parent_path)
        replacement = self._nodes_from_text(text)
        parent.children[index : index + 1] = replacement
        try:
            self._commit(render(self.document), before)
        except EditRejected:
            self.document = parse(before, path=self.path)
            raise

    def insert_lines(self, parent_path, index: int, text: str) -> tuple:
        """Insert raw text as new children; returns the path of the first one."""
        before = self.text
        parent = node_at(self.document, parent_path)
        children = getattr(parent, "children", None)
        if children is None:
            raise EditRejected("cannot insert here")
        index = max(0, min(index, len(children)))
        children[index:index] = self._nodes_from_text(text)
        try:
            self._commit(render(self.document), before)
        except EditRejected:
            self.document = parse(before, path=self.path)
            raise
        return tuple(parent_path) + (index,)

    def delete(self, path) -> None:
        before = self.text
        if not path:
            raise EditRejected("nothing selected")
        parent_path, index = path[:-1], path[-1]
        parent = node_at(self.document, parent_path)
        del parent.children[index]
        try:
            self._commit(render(self.document), before)
        except EditRejected:
            self.document = parse(before, path=self.path)
            raise

    # -- helpers -----------------------------------------------------------

    def _nodes_from_text(self, text: str) -> list[Node]:
        """Turn typed text into nodes, after checking it stands on its own.

        Validating only the whole file is not enough: an unterminated
        ``listen 80`` would silently merge with the line below it into one
        bad directive and still round trip. The fragment is therefore parsed
        in isolation first, where the missing ``;`` is an error.
        """
        if not text.strip():
            raise EditRejected("nothing to insert")
        fragment = parse(text)
        if fragment.errors:
            raise EditRejected("; ".join(fragment.errors))

        newline = self.newline
        return [Raw(raw=[line + newline]) for line in text.splitlines()]

    def indent_for(self, parent_path) -> str:
        """The indentation a new child of this parent should carry."""
        parent = node_at(self.document, parent_path)
        if isinstance(parent, Document):
            return ""
        unit = self.indent_unit()
        return getattr(parent, "indent", "") + unit

    def indent_unit(self) -> str:
        """Sniff the file's own indentation step, falling back to four spaces."""
        for node in self.document.walk():
            indent = getattr(node, "indent", "")
            if indent:
                return "\t" if indent.startswith("\t") else " " * len(indent)
        return "    "
