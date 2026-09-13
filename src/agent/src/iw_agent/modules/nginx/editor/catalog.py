"""What can be added, and where.

Nginx config is hierarchical — not everything belongs everywhere. The file
root cannot gain another ``server`` block from here (create a new site for
that). Inside a ``server`` you add ``listen`` / ``server_name`` / ``location``
blocks; inside ``location`` you add routing directives only.

Template lines use four spaces per level; the file's indent unit is applied
on insert so tab-indented configs stay tab-indented.
"""
from __future__ import annotations

from dataclasses import dataclass

from iw_agent.modules.nginx.confparse import Block, Directive, Document, Node
from iw_agent.modules.nginx.schemas import (
    DEFAULT_INDEX_FILES,
    TRY_FILES_SPA,
    TRY_FILES_STANDARD,
    SecurityPreset,
    security_headers_for_preset,
)

DOCUMENT_CONTEXT = ""
NEAR_LISTEN_CONTEXT = "near_listen"
NEAR_SERVER_NAME_CONTEXT = "near_server_name"
RAW_LINE = "__raw__"


@dataclass(frozen=True)
class InsertOption:
    label: str
    hint: str
    lines: tuple


def _headers(preset: SecurityPreset) -> tuple:
    return tuple(
        f'add_header {name} "{value}" always;'
        for name, value in security_headers_for_preset(preset)
    )


_PROXY_HEADERS = (
    "proxy_set_header Host $host;",
    "proxy_set_header X-Real-IP $remote_addr;",
    "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
    "proxy_set_header X-Forwarded-Proto $scheme;",
)

# File root — spacing and notes only (one server block per site file).
_DOCUMENT: tuple = ()

_NEAR_LISTEN: tuple = (
    InsertOption("listen", "another port for this server", ("listen 80;",)),
    InsertOption("listen — TLS", "port 443 with ssl", ("listen 443 ssl;",)),
    InsertOption(
        "listen — bind to an address",
        "restrict to one IP",
        ("listen 127.0.0.1:80;",),
    ),
)

_NEAR_SERVER_NAME: tuple = (
    InsertOption("server_name", "another hostname", ("server_name example.com;",)),
    InsertOption(
        "location — proxy",
        "forward a path to a backend",
        (
            "location / {",
            "    proxy_pass http://127.0.0.1:3000;",
            *(f"    {line}" for line in _PROXY_HEADERS),
            "}",
        ),
    ),
    InsertOption(
        "location — static",
        "serve files for a path",
        ("location / {", f"    try_files {TRY_FILES_STANDARD};", "}"),
    ),
    InsertOption(
        "return — redirect",
        "send visitors elsewhere",
        ("return 301 https://$host$request_uri;",),
    ),
)

_SERVER: tuple = (
    InsertOption("listen", "port this block answers on", ("listen 80;",)),
    InsertOption("listen — TLS", "port 443 with ssl", ("listen 443 ssl;",)),
    InsertOption(
        "listen — bind to an address",
        "restrict to one IP",
        ("listen 127.0.0.1:80;",),
    ),
    InsertOption("server_name", "hostnames served here", ("server_name example.com;",)),
    InsertOption("root", "directory files come from", ("root /var/www/example.com;",)),
    InsertOption("index", "files tried for a directory", (f"index {DEFAULT_INDEX_FILES};",)),
    InsertOption(
        "location — proxy",
        "forward a path to a backend",
        (
            "location / {",
            "    proxy_pass http://127.0.0.1:3000;",
            *(f"    {line}" for line in _PROXY_HEADERS),
            "}",
        ),
    ),
    InsertOption(
        "location — static",
        "serve files for a path",
        ("location / {", f"    try_files {TRY_FILES_STANDARD};", "}"),
    ),
    InsertOption(
        "location — single page app",
        "fall back to index.html",
        ("location / {", f"    try_files {TRY_FILES_SPA};", "}"),
    ),
    InsertOption(
        "return — redirect",
        "send visitors elsewhere",
        ("return 301 https://$host$request_uri;",),
    ),
    InsertOption(
        "TLS certificate",
        "certificate and key pair",
        (
            "ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;",
            "ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;",
        ),
    ),
    InsertOption(
        "security headers — basic",
        "a sensible baseline",
        _headers(SecurityPreset.BASIC),
    ),
    InsertOption(
        "security headers — strict",
        "baseline plus HSTS; needs HTTPS",
        _headers(SecurityPreset.STRICT),
    ),
    InsertOption(
        "client_max_body_size",
        "largest upload accepted",
        ("client_max_body_size 20m;",),
    ),
    InsertOption(
        "access_log",
        "where requests are logged",
        ("access_log /var/log/nginx/access.log;",),
    ),
    InsertOption(
        "error_log",
        "where errors are logged",
        ("error_log /var/log/nginx/error.log;",),
    ),
)

_LOCATION: tuple = (
    InsertOption(
        "proxy_pass with standard headers",
        "the usual reverse proxy set",
        ("proxy_pass http://127.0.0.1:3000;", *_PROXY_HEADERS),
    ),
    InsertOption("proxy_pass", "backend only", ("proxy_pass http://127.0.0.1:3000;",)),
    InsertOption("root", "serve files from here", ("root /var/www/example.com;",)),
    InsertOption(
        "alias",
        "map this path onto a directory",
        ("alias /var/www/assets;",),
    ),
    InsertOption(
        "try_files",
        "lookup order with a fallback",
        (f"try_files {TRY_FILES_STANDARD};",),
    ),
    InsertOption("index", "files tried for a directory", (f"index {DEFAULT_INDEX_FILES};",)),
    InsertOption(
        "add_header",
        "a response header",
        ('add_header X-Frame-Options "SAMEORIGIN" always;',),
    ),
    InsertOption("expires", "client cache lifetime", ("expires 30d;",)),
    InsertOption(
        "return",
        "answer without reaching a backend",
        ("return 404;",),
    ),
    InsertOption(
        "nested location",
        "a more specific path",
        ("location /health {", "    access_log off;", "}"),
    ),
)

_UPSTREAM: tuple = (
    InsertOption("server", "one backend in the pool", ("server 127.0.0.1:3000;",)),
    InsertOption("keepalive", "idle connections kept open", ("keepalive 32;",)),
    InsertOption("least_conn", "send to the least busy backend", ("least_conn;",)),
    InsertOption("ip_hash", "pin a client to one backend", ("ip_hash;",)),
)

_UNIVERSAL: tuple = (
    InsertOption("comment", "a note for whoever reads this next", ("# note",)),
    InsertOption("blank line", "spacing", ("",)),
)

_BY_CONTEXT: dict[str, tuple] = {
    DOCUMENT_CONTEXT: _DOCUMENT,
    NEAR_LISTEN_CONTEXT: _NEAR_LISTEN,
    NEAR_SERVER_NAME_CONTEXT: _NEAR_SERVER_NAME,
    "server": _SERVER,
    "location": _LOCATION,
    "upstream": _UPSTREAM,
}


def options_for(context: str) -> list[InsertOption]:
    """Legacy lookup by block name — prefer :func:`options_for_insert`."""
    return list(_BY_CONTEXT.get(context, ())) + list(_UNIVERSAL)


def options_for_insert(parent: Node, insert_index: int) -> list[InsertOption]:
    """Everything insertable at ``insert_index`` inside ``parent``."""
    if isinstance(parent, Document):
        return list(_DOCUMENT) + list(_UNIVERSAL)

    if isinstance(parent, Block):
        block_name = parent.name or "block"
        if insert_index > 0:
            previous = parent.children[insert_index - 1]
            if isinstance(previous, Directive):
                if previous.name == "listen" and block_name == "server":
                    return list(_NEAR_LISTEN) + list(_UNIVERSAL)
                if previous.name == "server_name" and block_name == "server":
                    return list(_NEAR_SERVER_NAME) + list(_UNIVERSAL)

        bucket = _BY_CONTEXT.get(block_name, ())
        return list(bucket) + list(_UNIVERSAL)

    return list(_UNIVERSAL)


def render_template(option: InsertOption, base_indent: str, unit: str) -> str:
    out = []
    for line in option.lines:
        stripped = line.lstrip(" ")
        if not stripped:
            out.append("")
            continue
        depth = (len(line) - len(stripped)) // 4
        out.append(base_indent + unit * depth + stripped)
    return "\n".join(out)
