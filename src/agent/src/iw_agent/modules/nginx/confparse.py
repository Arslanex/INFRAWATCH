"""Lossless parser for nginx config files.

The collectors and the executor both scan configs with line regexes and a
naive ``line.count("{") - line.count("}")`` depth counter. That is good enough
to patch a known directive, but it cannot back a structural editor: it loses
every position, it flattens nested blocks into their parent, and it miscounts
braces that sit inside comments or quoted strings.

This module is the single canonical parser. Two properties matter:

* **Lossless.** ``render(parse(text)) == text`` for any input. Unmodified
  nodes re-emit their original lines verbatim, so comments, blank lines,
  alignment and unusual formatting survive a round trip untouched.
* **Line-partitioned.** Every line of the file belongs to exactly one node.
  That is what lets an editor map a screen row to a node and back.

Statements that share a line (``listen 80; server_name x;``) and blocks that
open and close on one line (``if ($x) { return 404; }``) are kept as `Raw`
nodes: structurally opaque, still editable as text. Real configs put one
statement per line, and treating the exotic cases as raw keeps the lossless
guarantee cheap to hold.
"""
from __future__ import annotations

from dataclasses import dataclass, field

_QUOTES = "\"'"
_TERMINATORS = "{};"


class NginxParseError(Exception):
    """Raised only by :func:`check`; :func:`parse` itself never raises."""


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------


@dataclass
class Node:
    """One or more whole source lines.

    ``raw`` holds the original lines *with* their line endings, so rendering an
    untouched tree is a plain concatenation.
    """

    raw: list[str] = field(default_factory=list)
    span: tuple[int, int] | None = None
    parent: Node | None = field(default=None, repr=False, compare=False)
    dirty: bool = False

    @property
    def newline(self) -> str:
        for line in self.raw:
            if line.endswith("\r\n"):
                return "\r\n"
            if line.endswith("\n"):
                return "\n"
        return self.parent.newline if self.parent is not None else "\n"

    @property
    def kind(self) -> str:
        return type(self).__name__.lower()

    def render(self) -> list[str]:
        return list(self.raw)

    def walk(self):
        yield self
        for child in getattr(self, "children", ()):
            yield from child.walk()


@dataclass
class Blank(Node):
    """An empty or whitespace-only line."""


@dataclass
class Comment(Node):
    """A line whose first non-space character is ``#``."""

    text: str = ""


@dataclass
class Raw(Node):
    """A line the parser deliberately does not model (see module docstring)."""

    reason: str = ""


@dataclass
class Directive(Node):
    name: str = ""
    args: list[str] = field(default_factory=list)
    indent: str = ""
    comment: str = ""

    def render(self) -> list[str]:
        if not self.dirty:
            return list(self.raw)
        text = " ".join([self.name, *self.args]).rstrip()
        line = f"{self.indent}{text};"
        if self.comment:
            line = f"{line}  {self.comment}"
        return [line + self.newline]


@dataclass
class Block(Node):
    name: str = ""
    args: list[str] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    indent: str = ""
    header_raw: list[str] = field(default_factory=list)
    close_raw: list[str] = field(default_factory=list)
    comment: str = ""

    def render(self) -> list[str]:
        if self.dirty:
            text = " ".join([self.name, *self.args]).rstrip()
            header = f"{self.indent}{text} {{"
            if self.comment:
                header = f"{header}  {self.comment}"
            out = [header + self.newline]
        else:
            out = list(self.header_raw)
        for child in self.children:
            out.extend(child.render())
        if self.dirty:
            out.append(f"{self.indent}}}" + self.newline)
        else:
            out.extend(self.close_raw)
        return out


@dataclass
class Document(Node):
    children: list[Node] = field(default_factory=list)
    path: str | None = None
    errors: list[str] = field(default_factory=list)

    def render(self) -> list[str]:
        out: list[str] = []
        for child in self.children:
            out.extend(child.render())
        return out


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------


def split_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def scan(body: str, in_string: str | None = None):
    """Walk one line, honouring quotes, escapes and ``#`` comments.

    Returns ``(code, events, in_string, comment)`` where ``events`` lists the
    ``{``/``}``/``;`` characters that are real syntax rather than text inside a
    string or a comment.
    """
    events: list[tuple[str, int]] = []
    comment = ""
    code_end = len(body)
    escaped = False
    index = 0

    while index < len(body):
        char = body[index]
        if in_string is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
        elif char in _QUOTES:
            in_string = char
        elif char == "#":
            comment = body[index:]
            code_end = index
            break
        elif char in _TERMINATORS:
            events.append((char, index))
        index += 1

    return body[:code_end], events, in_string, comment


def split_args(code: str) -> list[str]:
    """Split directive arguments, keeping quoted runs together."""
    args: list[str] = []
    current = ""
    in_string: str | None = None
    escaped = False

    for char in code:
        if in_string is not None:
            current += char
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == in_string:
                in_string = None
            continue
        if char in _QUOTES:
            in_string = char
            current += char
            continue
        if char.isspace():
            if current:
                args.append(current)
                current = ""
            continue
        current += char

    if current:
        args.append(current)
    return args


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


class _Cursor:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.i = 0

    def eof(self) -> bool:
        return self.i >= len(self.lines)


class _Statement:
    """The lines from the cursor up to the first real ``{``, ``}`` or ``;``."""

    def __init__(self, char, raw, start, end, head_code, comment, tail):
        self.char = char          # terminator, or None at end of file
        self.raw = raw
        self.start = start
        self.end = end
        self.head_code = head_code  # code before the terminator, lines joined
        self.comment = comment
        self.tail = tail          # code after the terminator on the same line


def _indent_of(body: str) -> str:
    return body[: len(body) - len(body.lstrip())]


def _is_close_line(body: str) -> bool:
    code, events, _, _ = scan(body)
    return bool(events) and events[0][0] == "}" and not code[: events[0][1]].strip()


def _gather(cur: _Cursor) -> _Statement:
    start = cur.i
    raw: list[str] = []
    head_parts: list[str] = []
    in_string: str | None = None

    while cur.i < len(cur.lines):
        line = cur.lines[cur.i]
        body, _ = split_ending(line)
        code, events, in_string, comment = scan(body, in_string)
        raw.append(line)
        cur.i += 1
        if events:
            char, index = events[0]
            head_parts.append(code[:index])
            return _Statement(
                char,
                raw,
                start,
                cur.i - 1,
                " ".join(part.strip() for part in head_parts if part.strip()),
                comment,
                code[index + 1 :].strip(),
            )
        head_parts.append(code)

    return _Statement(
        None,
        raw,
        start,
        cur.i - 1,
        " ".join(part.strip() for part in head_parts if part.strip()),
        "",
        "",
    )


def _parse_children(cur: _Cursor, parent: Node, doc: Document, *, top: bool) -> list[Node]:
    children: list[Node] = []

    while not cur.eof():
        start = cur.i
        line = cur.lines[start]
        body, _ = split_ending(line)
        stripped = body.strip()

        if not stripped:
            cur.i += 1
            children.append(Blank(raw=[line], span=(start, start), parent=parent))
            continue

        if stripped.startswith("#"):
            cur.i += 1
            children.append(
                Comment(raw=[line], span=(start, start), parent=parent, text=stripped),
            )
            continue

        if _is_close_line(body):
            if not top:
                return children
            cur.i += 1
            doc.errors.append(f"line {start + 1}: unexpected '}}'")
            children.append(
                Raw(raw=[line], span=(start, start), parent=parent, reason="stray closing brace"),
            )
            continue

        statement = _gather(cur)

        if statement.char == "{" and not statement.tail:
            tokens = split_args(statement.head_code)
            block = Block(
                span=(statement.start, statement.end),
                parent=parent,
                name=tokens[0] if tokens else "",
                args=tokens[1:],
                indent=_indent_of(body),
                header_raw=list(statement.raw),
                comment=statement.comment,
                raw=list(statement.raw),
            )
            block.children = _parse_children(cur, block, doc, top=False)
            if cur.eof():
                doc.errors.append(f"line {statement.start + 1}: unclosed '{block.name}' block")
            else:
                block.close_raw = [cur.lines[cur.i]]
                cur.i += 1
            block.span = (statement.start, cur.i - 1)
            block.raw = list(cur.lines[statement.start : cur.i])
            children.append(block)
            continue

        if statement.char == ";" and not statement.tail:
            tokens = split_args(statement.head_code)
            children.append(
                Directive(
                    raw=list(statement.raw),
                    span=(statement.start, statement.end),
                    parent=parent,
                    name=tokens[0] if tokens else "",
                    args=tokens[1:],
                    indent=_indent_of(body),
                    comment=statement.comment,
                ),
            )
            continue

        reason = {
            "{": "block opens and closes on one line",
            ";": "more than one statement on a line",
            None: "no ';' before end of file",
        }.get(statement.char, "unrecognised syntax")
        if statement.char is None:
            doc.errors.append(f"line {statement.start + 1}: {reason}")
        children.append(
            Raw(
                raw=list(statement.raw),
                span=(statement.start, statement.end),
                parent=parent,
                reason=reason,
            ),
        )

    return children


def parse(text: str, *, path: str | None = None) -> Document:
    """Parse config text. Never raises — anything odd becomes a `Raw` node."""
    lines = text.splitlines(keepends=True)
    doc = Document(
        raw=list(lines),
        span=(0, len(lines) - 1) if lines else None,
        path=path,
    )
    doc.children = _parse_children(_Cursor(lines), doc, doc, top=True)
    return doc


def render(node: Node) -> str:
    return "".join(node.render())


def is_lossless(text: str) -> bool:
    """Whether this file survives a parse/render round trip untouched.

    The editor calls this before opening a file structurally: if the parser
    does not fully understand a config, it must not be the thing that rewrites
    it.
    """
    return render(parse(text)) == text


def check(text: str) -> None:
    """Raise :class:`NginxParseError` if the text is not safe to write."""
    doc = parse(text)
    if doc.errors:
        raise NginxParseError("; ".join(doc.errors))
    if render(doc) != text:
        raise NginxParseError("config did not survive a parse/render round trip")
