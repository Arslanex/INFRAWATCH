"""What can be added, and where.

This is the "+ add" row's menu. It is also where the concepts that used to
live behind nested pages survive: the security-header presets, the standard
proxy headers and the HTTPS redirect block are offered here as templates you
insert and can then see and tweak, rather than as hidden writes.

Template lines use four spaces per level; the file's own indent unit is
substituted when they are inserted, so a tab-indented config stays
tab-indented.
"""
from __future__ import annotations

from dataclasses import dataclass

from iw_agent.modules.nginx.schemas import (
    DEFAULT_INDEX_FILES,
    TRY_FILES_SPA,
    TRY_FILES_STANDARD,
    SecurityPreset,
    security_headers_for_preset,
)

DOCUMENT_CONTEXT = ""
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

_DOCUMENT: tuple = (
    InsertOption(
        "server block — reverse proxy",
        "listens on 80 and forwards to a local port",
        (
            "server {",
            "    listen 80;",
            "    listen [::]:80;",
            "    server_name example.com;",
            "",
            "    location / {",
            "        proxy_pass http://127.0.0.1:3000;",
            *(f"        {line}" for line in _PROXY_HEADERS),
            "    }",
            "}",
        ),
    ),
    InsertOption(
        "server block — static site",
        "serves files from a document root",
        (
            "server {",
            "    listen 80;",
            "    listen [::]:80;",
            "    server_name example.com;",
            "",
            "    root /var/www/example.com;",
            f"    index {DEFAULT_INDEX_FILES};",
            "",
            "    location / {",
            f"        try_files {TRY_FILES_STANDARD};",
            "    }",
            "}",
        ),
    ),
    InsertOption(
        "server block — HTTP to HTTPS redirect",
        "the companion block for a TLS site",
        (
            "server {",
            "    listen 80;",
            "    listen [::]:80;",
            "    server_name example.com;",
            "    return 301 https://$host$request_uri;",
            "}",
        ),
    ),
    InsertOption(
        "upstream block",
        "a named pool of backends",
        (
            "upstream backend {",
            "    server 127.0.0.1:3000;",
            "}",
        ),
    ),
)

_SERVER: tuple = (
    InsertOption("listen", "port this block answers on", ("listen 80;",)),
    InsertOption("listen — TLS", "port 443 with ssl", ("listen 443 ssl;",)),
    InsertOption("listen — bind to an address", "restrict to one IP",
                 ("listen 127.0.0.1:80;",)),
    InsertOption("server_name", "hostnames served here", ("server_name example.com;",)),
    InsertOption("root", "directory files come from", ("root /var/www/example.com;",)),
    InsertOption("index", "files tried for a directory",
                 (f"index {DEFAULT_INDEX_FILES};",)),
    InsertOption("location — proxy", "forward a path to a backend",
                 ("location / {", "    proxy_pass http://127.0.0.1:3000;",
                  *(f"    {line}" for line in _PROXY_HEADERS), "}")),
    InsertOption("location — static", "serve files for a path",
                 ("location / {", f"    try_files {TRY_FILES_STANDARD};", "}")),
    InsertOption("location — single page app", "fall back to index.html",
                 ("location / {", f"    try_files {TRY_FILES_SPA};", "}")),
    InsertOption("return — redirect", "send visitors elsewhere",
                 ("return 301 https://$host$request_uri;",)),
    InsertOption("TLS certificate", "certificate and key pair",
                 ("ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;",
                  "ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;")),
    InsertOption("security headers — basic", "a sensible baseline",
                 _headers(SecurityPreset.BASIC)),
    InsertOption("security headers — strict", "baseline plus HSTS; needs HTTPS",
                 _headers(SecurityPreset.STRICT)),
    InsertOption("client_max_body_size", "largest upload accepted",
                 ("client_max_body_size 20m;",)),
    InsertOption("access_log", "where requests are logged",
                 ("access_log /var/log/nginx/access.log;",)),
    InsertOption("error_log", "where errors are logged",
                 ("error_log /var/log/nginx/error.log;",)),
)

_LOCATION: tuple = (
    InsertOption("proxy_pass with standard headers", "the usual reverse proxy set",
                 ("proxy_pass http://127.0.0.1:3000;", *_PROXY_HEADERS)),
    InsertOption("proxy_pass", "backend only", ("proxy_pass http://127.0.0.1:3000;",)),
    InsertOption("root", "serve files from here", ("root /var/www/example.com;",)),
    InsertOption("alias", "map this path onto a directory",
                 ("alias /var/www/assets;",)),
    InsertOption("try_files", "lookup order with a fallback",
                 (f"try_files {TRY_FILES_STANDARD};",)),
    InsertOption("index", "files tried for a directory",
                 (f"index {DEFAULT_INDEX_FILES};",)),
    InsertOption("add_header", "a response header",
                 ('add_header X-Frame-Options "SAMEORIGIN" always;',)),
    InsertOption("expires", "client cache lifetime", ("expires 30d;",)),
    InsertOption("return", "answer without reaching a backend",
                 ("return 404;",)),
    InsertOption("nested location", "a more specific path",
                 ("location /health {", "    access_log off;", "}")),
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
    "server": _SERVER,
    "location": _LOCATION,
    "upstream": _UPSTREAM,
}


def options_for(context: str) -> list[InsertOption]:
    """Everything insertable inside a block of this name."""
    return list(_BY_CONTEXT.get(context, ())) + list(_UNIVERSAL)


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
