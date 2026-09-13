"""Typed edit forms for the directives we understand.

Each form turns the text a user types into validated arguments, reusing the
validators in :mod:`iw_agent.modules.nginx.validation` so the editor and the
programmatic action layer agree on what is acceptable.

Anything not listed here is edited as a raw line instead; the escape hatch is
checked by re-parsing rather than by a validator, because a raw line legally
contains the ``;`` that :func:`validate_directive_value` forbids.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from iw_agent.modules.nginx.collector import parse_listen_directive
from iw_agent.modules.nginx.confparse import split_args
from iw_agent.modules.nginx.validation import (
    NginxValidationError,
    validate_directive_value,
    validate_domain,
    validate_location_path,
    validate_port,
    validate_proxy_pass,
)

_SIZE_RE = re.compile(r"^\d+[kKmMgG]?$")
_TIME_RE = re.compile(r"^\d+(ms|s|m|h|d)?$")
_RETURN_CODE_RE = re.compile(r"^[1-5]\d\d$")
# nginx's own wildcards, which are not hostnames but are valid server names
_SERVER_NAME_SPECIAL = {"_", "*"}


@dataclass(frozen=True)
class DirectiveForm:
    name: str
    label: str
    help: str
    parse: Callable[[str], list[str]]
    placeholder: str = ""


def _fail(reason: str) -> "NginxValidationError":
    return NginxValidationError(reason)


def _server_names(value: str) -> list[str]:
    tokens = split_args(value)
    if not tokens:
        raise _fail("at least one server name is required")
    for token in tokens:
        if token in _SERVER_NAME_SPECIAL or token.startswith("*."):
            continue
        validate_domain(token, name="server name")
    return tokens


def _listen(value: str) -> list[str]:
    tokens = split_args(value)
    if not tokens:
        raise _fail("listen needs a port, optionally an address")
    endpoint = parse_listen_directive(" ".join(tokens))
    if endpoint is None:
        raise _fail("could not read a port out of that")
    validate_port(endpoint.port, name="listen port")
    return tokens


def _proxy_pass(value: str) -> list[str]:
    return [validate_proxy_pass(value.strip())]


def _absolute_path(label: str):
    def check(value: str) -> list[str]:
        text = validate_directive_value(value, name=label)
        if not text.startswith("/"):
            raise _fail(f"{label} must be an absolute path")
        return [text]

    return check


def _free_value(label: str, *, min_tokens: int = 1):
    def check(value: str) -> list[str]:
        text = validate_directive_value(value, name=label)
        tokens = split_args(text)
        if len(tokens) < min_tokens:
            raise _fail(f"{label} needs at least {min_tokens} values")
        return tokens

    return check


def _pattern(label: str, pattern: re.Pattern, hint: str):
    def check(value: str) -> list[str]:
        text = validate_directive_value(value, name=label)
        if not pattern.match(text):
            raise _fail(f"{label} should look like {hint}")
        return [text]

    return check


def _return(value: str) -> list[str]:
    tokens = split_args(validate_directive_value(value, name="return"))
    if not tokens or not _RETURN_CODE_RE.match(tokens[0]):
        raise _fail("return starts with a status code, e.g. 301")
    return tokens


def _add_header(value: str) -> list[str]:
    tokens = split_args(validate_directive_value(value, name="add_header"))
    if len(tokens) < 2:
        raise _fail("add_header needs a name and a value")
    return tokens


def _location(value: str) -> list[str]:
    tokens = split_args(value.strip())
    if not tokens:
        raise _fail("location needs a path")
    if len(tokens) == 1:
        return [validate_location_path(tokens[0])]
    modifier, path = tokens[0], " ".join(tokens[1:])
    if modifier not in {"=", "~", "~*", "^~", "@"}:
        raise _fail("modifier must be one of =  ~  ~*  ^~  @")
    if modifier in {"~", "~*"}:
        return [modifier, validate_directive_value(path, name="location pattern")]
    return [modifier, validate_location_path(path)]


DIRECTIVE_FORMS: dict[str, DirectiveForm] = {
    form.name: form
    for form in (
        DirectiveForm("server_name", "Server names",
                      "Hostnames this block answers for, separated by spaces",
                      _server_names, "example.com www.example.com"),
        DirectiveForm("listen", "Listen",
                      "Port, optionally an address and ssl",
                      _listen, "80  ·  443 ssl  ·  127.0.0.1:8080"),
        DirectiveForm("proxy_pass", "Backend",
                      "Where matching requests are forwarded",
                      _proxy_pass, "http://127.0.0.1:3000"),
        DirectiveForm("root", "Document root",
                      "Directory files are served from",
                      _absolute_path("root"), "/var/www/example.com"),
        DirectiveForm("alias", "Alias",
                      "Directory this location maps onto",
                      _absolute_path("alias"), "/var/www/assets"),
        DirectiveForm("index", "Index files",
                      "Files tried when a directory is requested",
                      _free_value("index"), "index.html index.htm"),
        DirectiveForm("try_files", "Try files",
                      "Lookup order, ending in a fallback",
                      _free_value("try_files", min_tokens=2), "$uri $uri/ =404"),
        DirectiveForm("ssl_certificate", "Certificate",
                      "Full chain certificate file",
                      _absolute_path("ssl_certificate"),
                      "/etc/letsencrypt/live/example.com/fullchain.pem"),
        DirectiveForm("ssl_certificate_key", "Certificate key",
                      "Private key file",
                      _absolute_path("ssl_certificate_key"),
                      "/etc/letsencrypt/live/example.com/privkey.pem"),
        DirectiveForm("add_header", "Response header",
                      "Header name then value",
                      _add_header, 'X-Frame-Options "SAMEORIGIN" always'),
        DirectiveForm("proxy_set_header", "Proxy header",
                      "Header passed on to the backend",
                      _add_header, "Host $host"),
        DirectiveForm("return", "Return",
                      "Status code, then a target for redirects",
                      _return, "301 https://$host$request_uri"),
        DirectiveForm("client_max_body_size", "Max body size",
                      "Largest request body accepted",
                      _pattern("client_max_body_size", _SIZE_RE, "20m"), "20m"),
        DirectiveForm("proxy_read_timeout", "Read timeout",
                      "How long to wait for the backend",
                      _pattern("proxy_read_timeout", _TIME_RE, "60s"), "60s"),
        DirectiveForm("keepalive_timeout", "Keepalive timeout",
                      "How long idle connections are held",
                      _pattern("keepalive_timeout", _TIME_RE, "65s"), "65s"),
        DirectiveForm("access_log", "Access log",
                      "Where requests are logged",
                      _free_value("access_log"), "/var/log/nginx/access.log"),
        DirectiveForm("error_log", "Error log",
                      "Where errors are logged",
                      _free_value("error_log"), "/var/log/nginx/error.log"),
        DirectiveForm("expires", "Expires",
                      "Cache lifetime sent to clients",
                      _free_value("expires"), "30d"),
    )
}

BLOCK_FORMS: dict[str, DirectiveForm] = {
    "location": DirectiveForm(
        "location", "Location path",
        "Path prefix, or a modifier and a pattern",
        _location, "/api   ·   ~ \\.php$   ·   ^~ /static",
    ),
}


def form_for(name: str, *, block: bool = False) -> DirectiveForm | None:
    return (BLOCK_FORMS if block else DIRECTIVE_FORMS).get(name)
