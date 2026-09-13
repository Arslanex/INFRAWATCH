"""The parser must be lossless before anything is allowed to rewrite a config."""
import pathlib

import pytest

from iw_agent.modules.nginx.confparse import (
    Blank,
    Block,
    Comment,
    Directive,
    NginxParseError,
    Raw,
    check,
    is_lossless,
    parse,
    render,
    scan,
    split_args,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nginx"
FIXTURE_FILES = sorted(FIXTURES.glob("*.conf"))
assert FIXTURE_FILES, "fixture corpus is missing"


def _read(name: str) -> str:
    # read bytes: Path.read_text has no newline= before 3.13, and these
    # fixtures deliberately carry CRLF and missing trailing newlines
    return (FIXTURES / name).read_bytes().decode("utf-8")


# --- the core guarantee ---------------------------------------------------

@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_round_trip_is_byte_exact(path):
    text = path.read_bytes().decode("utf-8")
    assert render(parse(text)) == text


@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_every_line_belongs_to_exactly_one_node(path):
    """The editor maps screen rows to nodes, so lines must partition cleanly."""
    text = path.read_bytes().decode("utf-8")
    line_count = len(text.splitlines())
    doc = parse(text)

    owned = []
    for node in doc.walk():
        if isinstance(node, (Directive, Comment, Blank, Raw)):
            start, end = node.span
            owned.extend(range(start, end + 1))
        elif isinstance(node, Block):
            start, _ = node.span
            owned.append(start)                       # header
            if node.close_raw:
                owned.append(node.span[1])            # closing brace

    assert sorted(owned) == list(range(line_count))


# --- cases the current brace counter gets wrong ---------------------------

def test_closing_brace_in_a_comment_does_not_end_the_block():
    doc = parse(_read("tricky_quotes.conf"))
    server = doc.children[0]

    assert isinstance(server, Block)
    assert server.name == "server"
    # the block survives past both "}" comments and reaches its location block
    assert any(isinstance(c, Block) and c.name == "location" for c in server.children)


def test_braces_and_semicolons_inside_quoted_values_are_text():
    doc = parse(_read("tricky_quotes.conf"))
    headers = [
        node
        for node in doc.walk()
        if isinstance(node, Directive) and node.name == "add_header"
    ]

    assert [h.args[0] for h in headers] == ["X-Odd", "X-Hash", "X-Quote"]
    assert headers[0].args[1] == '"a;b{c}d"'
    assert headers[1].args[1] == '"https://x/#fragment"'


def test_hash_inside_a_quoted_string_is_not_a_comment():
    code, _, _, comment = scan('    add_header X "https://x/#frag";')
    assert comment == ""
    assert code.endswith(";")


# --- structure ------------------------------------------------------------

def test_nested_locations_stay_nested():
    doc = parse(_read("nested_location.conf"))
    server = doc.children[0]
    api = next(c for c in server.children if isinstance(c, Block) and c.args == ["/api"])
    inner = [c for c in api.children if isinstance(c, Block)]

    assert len(inner) == 1
    assert inner[0].args == ["/api/health"]
    # the nested proxy_pass belongs to the child, not the parent
    assert [d.args[0] for d in api.children if isinstance(d, Directive) and d.name == "proxy_pass"] == [
        "http://127.0.0.1:9000",
    ]


def test_non_server_blocks_are_modelled():
    doc = parse(_read("upstream_map.conf"))
    blocks = [c for c in doc.children if isinstance(c, Block)]

    assert [b.name for b in blocks] == ["upstream", "map", "server"]
    assert blocks[0].args == ["backend"]
    assert blocks[1].args == ["$http_upgrade", "$connection_upgrade"]


def test_directive_fields():
    doc = parse(_read("simple_proxy.conf"))
    server = doc.children[1]
    listen = server.children[0]

    assert isinstance(listen, Directive)
    assert listen.name == "listen"
    assert listen.args == ["80"]
    assert listen.indent == "    "
    assert listen.span == (2, 2)


def test_trailing_comment_is_kept_separate():
    doc = parse("server {\n    proxy_pass http://x;  # backend\n}\n")
    directive = doc.children[0].children[0]

    assert directive.args == ["http://x"]
    assert directive.comment == "# backend"


def test_blank_lines_and_comments_are_nodes():
    doc = parse(_read("simple_proxy.conf"))

    assert isinstance(doc.children[0], Comment)
    assert any(isinstance(c, Blank) for c in doc.children[1].children)


# --- deliberately unmodelled shapes stay editable as text -----------------

def test_inline_block_becomes_raw():
    doc = parse(_read("inline_block.conf"))
    raws = [n for n in doc.walk() if isinstance(n, Raw)]

    assert len(raws) == 2
    assert all("one line" in n.reason for n in raws)


def test_two_statements_on_one_line_become_raw():
    doc = parse(_read("multi_statement_line.conf"))
    raws = [n for n in doc.walk() if isinstance(n, Raw)]

    assert len(raws) == 1
    assert "more than one statement" in raws[0].reason


# --- line endings and edges ----------------------------------------------

def test_crlf_survives():
    text = _read("crlf.conf")
    assert "\r\n" in text
    assert render(parse(text)) == text


def test_missing_trailing_newline_survives():
    text = _read("no_trailing_newline.conf")
    assert not text.endswith("\n")
    assert render(parse(text)) == text


def test_empty_file():
    doc = parse("")
    assert doc.children == []
    assert render(doc) == ""


# --- editing renders from fields -----------------------------------------

def test_editing_a_directive_rewrites_only_that_line():
    text = _read("simple_proxy.conf")
    doc = parse(text)
    proxy = next(
        n for n in doc.walk() if isinstance(n, Directive) and n.name == "proxy_pass"
    )
    proxy.args = ["http://127.0.0.1:4000"]
    proxy.dirty = True

    before = text.splitlines()
    after = render(doc).splitlines()

    assert len(before) == len(after)
    changed = [i for i, (b, a) in enumerate(zip(before, after)) if b != a]
    assert len(changed) == 1
    assert after[changed[0]] == "        proxy_pass http://127.0.0.1:4000;"


def test_editing_preserves_a_trailing_comment():
    doc = parse("server {\n    proxy_pass http://x;  # backend\n}\n")
    directive = doc.children[0].children[0]
    directive.args = ["http://y"]
    directive.dirty = True

    assert "proxy_pass http://y;  # backend" in render(doc)


def test_editing_a_block_header():
    doc = parse(_read("nested_location.conf"))
    api = next(n for n in doc.walk() if isinstance(n, Block) and n.args == ["/api"])
    api.args = ["/v2"]
    api.dirty = True
    out = render(doc)

    assert "location /v2 {" in out
    assert "location /api/health {" in out       # the child is untouched


# --- the safety valve -----------------------------------------------------

@pytest.mark.parametrize("path", FIXTURE_FILES, ids=lambda p: p.name)
def test_is_lossless_accepts_the_corpus(path):
    assert is_lossless(path.read_bytes().decode("utf-8")) is True


def test_check_rejects_an_unclosed_block():
    with pytest.raises(NginxParseError, match="unclosed"):
        check("server {\n    listen 80;\n")


def test_check_rejects_a_stray_closing_brace():
    with pytest.raises(NginxParseError, match="unexpected"):
        check("server {\n    listen 80;\n}\n}\n")


def test_check_accepts_the_corpus():
    for path in FIXTURE_FILES:
        check(path.read_bytes().decode("utf-8"))


# --- argument splitting ---------------------------------------------------

@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("try_files $uri $uri/ =404", ["try_files", "$uri", "$uri/", "=404"]),
        ('add_header X "a b c"', ["add_header", "X", '"a b c"']),
        ("listen [::]:443 ssl", ["listen", "[::]:443", "ssl"]),
        ("   spaced    out   ", ["spaced", "out"]),
        ("", []),
    ],
)
def test_split_args(code, expected):
    assert split_args(code) == expected
