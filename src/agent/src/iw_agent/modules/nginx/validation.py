"""Input validation for the nginx executor.

The executor is the transport-agnostic entry point: today the CLI drives it,
tomorrow core does over a WebSocket. Anything it reads out of
``ActionRequest.params`` is therefore untrusted, and most of it ends up either
in an argv that runs as root or verbatim inside a server config. Validation
lives here rather than in the CLI so both callers get the same guarantees.
"""
from __future__ import annotations

import os
import re

from iw_agent.core.exceptions import NginxError

DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
)
EMAIL_RE = re.compile(r"^[^@\s,;]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
BINARY_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
PROXY_PASS_RE = re.compile(
    r"^(https?://[a-zA-Z0-9._-]+(:\d{1,5})?(/[^\s;{}]*)?"
    r"|unix:/[^\s;{}:]+:(/[^\s;{}]*)?)$",
)
LOCATION_PATH_RE = re.compile(r"^/[^\s;{}]*$")

# a value spliced into a config must not be able to close the directive it
# sits in, open a new block, or comment the rest of the line out
_CONFIG_INJECTION_CHARS = (";", "{", "}", "#", "\n", "\r", "\x00")

# absolute program paths are accepted only from these directories
ALLOWED_BINARY_DIRS = frozenset(
    {"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/local/bin", "/usr/local/sbin"},
)

# realpaths the executor is allowed to write to or read configs from
DEFAULT_ALLOWED_CONFIG_ROOTS = ("/etc/nginx", "/usr/local/etc/nginx", "/etc/letsencrypt")


class NginxValidationError(NginxError):
    code = "NGINX_INVALID_PARAM"


def _fail(name: str, value: object, reason: str) -> "NginxValidationError":
    return NginxValidationError(f"invalid {name} {value!r}: {reason}")


def validate_domain(value: object, *, name: str = "domain") -> str:
    text = str(value or "").strip().lower()
    if not text:
        raise _fail(name, value, "must not be empty")
    if len(text) > 253:
        raise _fail(name, value, "longer than 253 characters")
    if not DOMAIN_RE.match(text):
        raise _fail(name, value, "not a valid hostname")
    return text


def validate_server_names(values: object, *, domain: str) -> list[str]:
    if values is None:
        return [domain]
    if isinstance(values, str) or not isinstance(values, (list, tuple)):
        raise _fail("server_names", values, "must be a list of hostnames")
    names = [validate_domain(item, name="server_name") for item in values]
    return names or [domain]


def validate_email(value: object) -> str:
    text = str(value or "").strip()
    if not EMAIL_RE.match(text):
        raise _fail("email", value, "not a valid email address")
    return text


def validate_port(value: object, *, name: str = "port") -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise _fail(name, value, "must be an integer") from None
    if not 1 <= port <= 65535:
        raise _fail(name, value, "must be between 1 and 65535")
    return port


def validate_binary(value: object, *, name: str) -> str:
    """Accept a bare program name, or an absolute path inside a system bin dir.

    A bare name is resolved against PATH by the caller. An absolute path is
    allowed so operators can point at a non-packaged build, but only from the
    directories a system binary would live in -- these argv entries run as
    root, so an arbitrary path here is arbitrary code execution.
    """
    text = str(value or "").strip()
    if not text:
        raise _fail(name, value, "must not be empty")

    if text.startswith("/"):
        normalized = os.path.normpath(text)
        if normalized != text:
            raise _fail(name, value, "must be a normalized absolute path")
        parent = os.path.dirname(normalized)
        if parent not in ALLOWED_BINARY_DIRS:
            raise _fail(name, value, f"must live in one of {sorted(ALLOWED_BINARY_DIRS)}")
        if not BINARY_NAME_RE.match(os.path.basename(normalized)):
            raise _fail(name, value, "unexpected characters in program name")
        return normalized

    if not BINARY_NAME_RE.match(text):
        raise _fail(name, value, "must be a bare program name or an absolute path")
    return text


def validate_directory(value: object, *, name: str) -> str:
    """An absolute, traversal-free directory.

    Traversal is rejected rather than normalized away: a legitimate operator
    setting never contains "..", so its presence is worth refusing outright
    instead of silently resolving to somewhere else.
    """
    text = str(value or "").strip()
    if not text.startswith("/"):
        raise _fail(name, value, "must be an absolute path")
    if ".." in text.split("/"):
        raise _fail(name, value, "must not traverse upwards")
    return os.path.normpath(text)


def validate_directive_value(value: object, *, name: str) -> str:
    text = str(value if value is not None else "")
    for char in _CONFIG_INJECTION_CHARS:
        if char in text:
            raise _fail(name, value, "contains a character that would break out of the directive")
    if not text.strip():
        raise _fail(name, value, "must not be empty")
    return text.strip()


def validate_proxy_pass(value: object) -> str:
    text = validate_directive_value(value, name="proxy_pass")
    if not PROXY_PASS_RE.match(text):
        raise _fail("proxy_pass", value, "must be an http(s):// or unix: upstream")
    return text


def validate_location_path(value: object) -> str:
    text = validate_directive_value(value, name="location path")
    if not LOCATION_PATH_RE.match(text):
        raise _fail("location path", value, "must start with / and contain no config syntax")
    return text


def validate_config_path(
    value: object,
    *,
    allowed_roots: tuple[str, ...] = DEFAULT_ALLOWED_CONFIG_ROOTS,
    name: str = "config_path",
) -> str:
    """Resolve a config path and confirm it sits under a known nginx root.

    Symlinks are resolved first, so a link planted inside sites-enabled cannot
    be used to steer a write somewhere else.
    """
    text = str(value or "").strip()
    if not text.startswith("/"):
        raise _fail(name, value, "must be an absolute path")

    resolved = os.path.realpath(text)
    for root in allowed_roots:
        root_real = os.path.realpath(root)
        if resolved == root_real or resolved.startswith(root_real + os.sep):
            return resolved
    raise _fail(name, value, f"outside the allowed nginx roots {list(allowed_roots)}")


def validate_timeout(value: object, *, name: str = "timeout") -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError):
        raise _fail(name, value, "must be a number") from None
    if not 0 < timeout <= 3600:
        raise _fail(name, value, "must be between 0 and 3600 seconds")
    return timeout
