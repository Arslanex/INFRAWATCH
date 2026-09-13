"""Human explanations for the editor's right-hand panel.

Each selected row gets three short answers:
  - what the line *is*
  - what editing it *changes* on the server
  - what *add* inserts at this spot
"""
from __future__ import annotations

from dataclasses import dataclass

from iw_agent.modules.nginx.confparse import Block, Comment, Directive, Document, Node, Raw
from iw_agent.modules.nginx.editor.catalog import DOCUMENT_CONTEXT, options_for
from iw_agent.modules.nginx.editor.forms import form_for
from iw_agent.modules.nginx.editor.rows import Row, RowKind


@dataclass(frozen=True)
class RowHint:
    title: str
    what: str
    changes: str
    add_here: str


_BLOCK_HINTS = {
    "server": RowHint(
        title="server block",
        what="One website (or redirect) — names, ports, and routing live here.",
        changes="Edits affect every request that matches this block's names and ports.",
        add_here="listen, server_name, location, TLS, logs, redirects",
    ),
    "location": RowHint(
        title="location block",
        what="Rules for URLs matching this path prefix or pattern.",
        changes="Edits affect only requests whose path matches this location.",
        add_here="proxy_pass, root, try_files, headers, nested location",
    ),
    "upstream": RowHint(
        title="upstream block",
        what="A named pool of backend servers for load balancing.",
        changes="Edits affect every proxy_pass that points at this upstream name.",
        add_here="server, keepalive, least_conn, ip_hash",
    ),
}

_DIRECTIVE_HINTS = {
    "server_name": RowHint(
        title="server_name",
        what="Hostnames nginx matches before using this server block.",
        changes="Changes which domain names reach this site (DNS must point here too).",
        add_here="another listen line, locations, TLS certificates",
    ),
    "listen": RowHint(
        title="listen",
        what="IP and port nginx binds to for this block.",
        changes="Changes which port (and whether TLS) clients connect on.",
        add_here="server_name, locations, SSL settings",
    ),
    "proxy_pass": RowHint(
        title="proxy_pass",
        what="Backend URL where nginx forwards requests.",
        changes="Changes where your app receives traffic (host, port, or upstream name).",
        add_here="proxy headers, timeouts, nested location",
    ),
    "root": RowHint(
        title="root",
        what="Directory on disk used to serve static files.",
        changes="Changes which folder nginx reads HTML/assets from.",
        add_here="index, try_files, location blocks",
    ),
    "alias": RowHint(
        title="alias",
        what="Maps this location's URL path to a different directory.",
        changes="Changes the folder served for this path without changing the URL.",
        add_here="try_files, expires, add_header",
    ),
    "index": RowHint(
        title="index",
        what="Default filenames tried when a directory is requested.",
        changes="Changes which file opens for `/` or folder URLs.",
        add_here="try_files, root, location blocks",
    ),
    "try_files": RowHint(
        title="try_files",
        what="Order nginx looks up files before falling back or erroring.",
        changes="Changes SPA routing, 404 behaviour, or static fallbacks.",
        add_here="index, root, proxy_pass",
    ),
    "ssl_certificate": RowHint(
        title="ssl_certificate",
        what="Path to the public TLS certificate chain.",
        changes="Changes which cert browsers see for HTTPS on this site.",
        add_here="ssl_certificate_key, listen 443 ssl, security headers",
    ),
    "ssl_certificate_key": RowHint(
        title="ssl_certificate_key",
        what="Path to the private key for this certificate.",
        changes="Must pair with ssl_certificate — wrong key breaks HTTPS.",
        add_here="ssl_certificate, listen 443 ssl",
    ),
    "return": RowHint(
        title="return",
        what="Immediate response without reaching a backend (often redirects).",
        changes="Changes redirect targets or fixed status answers (301, 404, …).",
        add_here="listen, server_name, another location",
    ),
    "add_header": RowHint(
        title="add_header",
        what="HTTP response header sent to the browser.",
        changes="Changes security headers, CORS, caching hints, etc.",
        add_here="more headers, proxy_pass, try_files",
    ),
    "proxy_set_header": RowHint(
        title="proxy_set_header",
        what="Header nginx forwards to the backend application.",
        changes="Changes what your app sees (Host, client IP, HTTPS flag, …).",
        add_here="proxy_pass, timeouts, more proxy headers",
    ),
    "client_max_body_size": RowHint(
        title="client_max_body_size",
        what="Maximum upload/request body size accepted.",
        changes="Raises or lowers the largest file upload allowed.",
        add_here="proxy_pass, timeouts, locations",
    ),
    "proxy_read_timeout": RowHint(
        title="proxy_read_timeout",
        what="How long nginx waits for the backend to respond.",
        changes="Longer helps slow APIs; shorter fails fast on hung backends.",
        add_here="proxy_pass, proxy headers",
    ),
    "keepalive_timeout": RowHint(
        title="keepalive_timeout",
        what="How long idle client connections stay open.",
        changes="Affects connection reuse and resource usage.",
        add_here="listen, server_name, locations",
    ),
    "access_log": RowHint(
        title="access_log",
        what="Where request access logs are written.",
        changes="Changes log file path or disables logging for this scope.",
        add_here="error_log, locations, return",
    ),
    "error_log": RowHint(
        title="error_log",
        what="Where nginx error messages are written.",
        changes="Changes which file receives error/debug output.",
        add_here="access_log, locations",
    ),
    "expires": RowHint(
        title="expires",
        what="Cache-Control lifetime sent to browsers for static files.",
        changes="Changes how long clients cache assets without re-fetching.",
        add_here="root, try_files, add_header",
    ),
}


def hint_for_row(row: Row) -> RowHint:
    if row.kind is RowKind.ADD_SLOT:
        return _add_slot_hint(row)

    node = row.node
    if isinstance(node, Directive):
        return _directive_hint(node)
    if isinstance(node, Block):
        return _block_hint(node, row)
    if isinstance(node, Raw):
        return RowHint(
            title="raw line",
            what="Nginx syntax the editor could not split into a typed field.",
            changes="Editing re-parses the whole line — check nginx -t after save.",
            add_here=_add_options_summary(row.insert_parent or _parent_from_path(row)),
        )
    if isinstance(node, Comment):
        return RowHint(
            title="comment",
            what="A note for humans — nginx ignores it.",
            changes="Safe to edit; does not affect traffic.",
            add_here="directives or blank lines nearby",
        )
    return RowHint(
        title="blank line",
        what="Spacing in the config file.",
        changes="Removing it only affects readability.",
        add_here=_add_options_summary(_parent_from_row(row)),
    )


def _directive_hint(node: Directive) -> RowHint:
    base = _DIRECTIVE_HINTS.get(node.name)
    form = form_for(node.name)
    if base is not None:
        return base
    if form is not None:
        return RowHint(
            title=form.label,
            what=form.help,
            changes=f"Updates the `{node.name}` setting for this block.",
            add_here=_add_options_summary(_guess_parent_name(node.name)),
        )
    return RowHint(
        title=node.name,
        what="An nginx directive in this block.",
        changes=f"Editing changes how `{node.name}` behaves for matching requests.",
        add_here="related directives, locations, comments",
    )


def _block_hint(node: Block, row: Row) -> RowHint:
    base = _BLOCK_HINTS.get(node.name)
    form = form_for(node.name, block=True)
    if row.kind is RowKind.BLOCK_OPEN and form is not None:
        return RowHint(
            title=form.label,
            what=form.help,
            changes=_BLOCK_HINTS.get(node.name, base or RowHint("", "", "", "")).changes
            or "Edits affect routing inside this block.",
            add_here=_add_options_summary(node),
        )
    if base is not None:
        return base
    args = " ".join(node.args)
    title = f"{node.name} {args}".strip()
    return RowHint(
        title=title,
        what=f"A `{node.name}` block grouping nested settings.",
        changes="Edits inside affect everything nested in this block.",
        add_here=_add_options_summary(node),
    )


def _add_slot_hint(row: Row) -> RowHint:
    parent = row.insert_parent
    if parent is None:
        parent_name = "file"
    elif isinstance(parent, Document):
        parent_name = "file"
    else:
        parent_name = getattr(parent, "name", "") or "block"

    options = options_for(
        DOCUMENT_CONTEXT if isinstance(parent, Document) else getattr(parent, "name", ""),
    )
    preview = ", ".join(option.label for option in options[:5])
    if len(options) > 5:
        preview = f"{preview}, …"

    if isinstance(parent, Document):
        what = "End of the config file — new top-level blocks go here."
        changes = "Adding inserts a new server or upstream block into this file."
    elif getattr(parent, "name", "") == "server":
        what = "Inside a server block — new directives or locations go here."
        changes = "Adding changes how this website handles matching requests."
    elif getattr(parent, "name", "") == "location":
        what = "Inside a location — routing and response rules go here."
        changes = "Adding changes behaviour for this URL path only."
    else:
        what = f"Inside `{parent_name}` — new lines insert at this position."
        changes = "Adding changes settings scoped to this block."

    return RowHint(
        title="add here",
        what=what,
        changes=changes,
        add_here=preview or "directives from the template menu",
    )


def _add_options_summary(parent) -> str:
    if parent is None:
        return "directives, comments"
    if isinstance(parent, Document):
        context = DOCUMENT_CONTEXT
    elif isinstance(parent, str):
        context = parent
    else:
        context = getattr(parent, "name", "") or ""
    options = options_for(context)
    if not options:
        return "directives, comments"
    labels = [option.label for option in options[:4]]
    text = ", ".join(labels)
    if len(options) > 4:
        text = f"{text}, …"
    return text


def _parent_from_row(row: Row) -> Node | str | None:
    if row.insert_parent is not None:
        return row.insert_parent
    return _parent_from_path(row)


def _parent_from_path(row: Row) -> Node | str | None:
    if len(row.path) <= 1:
        return DOCUMENT_CONTEXT
    return "block"


def _guess_parent_name(_directive_name: str) -> str:
    return "server"
