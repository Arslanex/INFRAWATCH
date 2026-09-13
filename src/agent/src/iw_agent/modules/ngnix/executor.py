from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from iw_agent.core._thread import read
from iw_agent.core.action_service import get_action_service
from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.commands import is_command_available, run_command
from iw_agent.modules.ngnix.collector import (
    DEFAULT_NGINX_BINARY,
    DEFAULT_NGINX_TIMEOUT_SECONDS,
    DEFAULT_SITES_AVAILABLE_DIR,
    DEFAULT_SITES_ENABLED_DIR,
    _extract_server_blocks,
    _is_http_redirect_block,
    _is_www_redirect_block,
    collect_virtual_hosts,
    precheck_certificate_domain,
)
from iw_agent.modules.ngnix.schemas import (
    DEFAULT_INDEX_FILES,
    MANAGED_SECURITY_HEADER_NAMES,
    SecurityPreset,
    SiteKind,
    TRY_FILES_STANDARD,
    VirtualHost,
    security_headers_for_preset,
)
from iw_agent.modules.ssl.executor import CertbotRequest, obtain_certificate, renew_certificate

MODULE = "ngnix"

NGINX_SITE_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="view_details",
        label="View site details",
        kind=ActionKind.READ,
        description="Show parsed virtual host fields from collector data",
    ),
    ActionSpec(
        id="test_config",
        label="Test nginx config",
        kind=ActionKind.WRITE,
        requires_root=False,
        description="Run nginx -t before any reload",
    ),
    ActionSpec(
        id="reload",
        label="Reload nginx",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="nginx -t then systemctl reload nginx (or nginx -s reload)",
    ),
    ActionSpec(
        id="enable_site",
        label="Enable site",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Symlink sites-available to sites-enabled, then reload",
    ),
    ActionSpec(
        id="disable_site",
        label="Disable site",
        kind=ActionKind.DESTRUCTIVE,
        requires_root=True,
        double_confirm=True,
        description="Remove sites-enabled symlink, then reload",
    ),
    ActionSpec(
        id="attach_ssl",
        label="Attach certificate to nginx",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Add ssl_certificate directives for a Let's Encrypt domain",
    ),
    ActionSpec(
        id="secure_site",
        label="Obtain HTTPS certificate",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="certbot obtain, attach cert to nginx, test and reload",
    ),
    ActionSpec(
        id="renew_site",
        label="Renew certificate",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="certbot renew for this site, then reload nginx",
    ),
    ActionSpec(
        id="apply_redirect_settings",
        label="Update redirect settings",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Enable or disable HTTP→HTTPS and www redirects",
    ),
    ActionSpec(
        id="apply_backend_settings",
        label="Update backend settings",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Set proxy_pass or document root for the site",
    ),
    ActionSpec(
        id="apply_security_settings",
        label="Update security headers",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Apply Basic or Strict security header presets",
    ),
    ActionSpec(
        id="apply_static_settings",
        label="Update static file settings",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Set document root, index files, and try_files for static sites",
    ),
    ActionSpec(
        id="create_site",
        label="Create new site",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Write a new sites-available config and optionally enable it",
    ),
)

HIDDEN_ACTION_IDS = frozenset(
    {
        "apply_redirect_settings",
        "apply_backend_settings",
        "apply_security_settings",
        "apply_static_settings",
        "create_site",
    },
)

NGINX_ACTIONS_BY_ID = {action.id: action for action in NGINX_SITE_ACTIONS}

SERVER_BLOCK_START = re.compile(r"^\s*server\s*\{")
SERVER_NAME = re.compile(r"^\s*server_name\s+(?P<names>.+);")
LISTEN_443 = re.compile(r"^\s*listen\s+.*443")
REDIRECT_RETURN = re.compile(r"^\s*return\s+301\s+https://")
PROXY_PASS_LINE = re.compile(r"^(\s*)proxy_pass\s+([^;]+);\s*$")
ROOT_LINE = re.compile(r"^(\s*)root\s+([^;]+);\s*$")
INDEX_LINE = re.compile(r"^(\s*)index\s+([^;]+);\s*$")
TRY_FILES_LINE = re.compile(r"^(\s*)try_files\s+([^;]+);\s*$")
LOCATION_ROOT_START = re.compile(r"^\s*location\s+/\s*\{")
ADD_HEADER_LINE = re.compile(
    r'^\s*add_header\s+(?P<name>[^;\s]+)\s+"(?P<value>[^"]*)"(?:\s+always)?\s*;\s*$',
)


@dataclass(frozen=True)
class DeployResult:
    changed: bool
    message: str
    backup_path: str | None = None


def _cert_paths(domain: str, live_dir: str = "/etc/letsencrypt/live") -> tuple[str, str]:
    base = f"{live_dir.rstrip('/')}/{domain}"
    return f"{base}/fullchain.pem", f"{base}/privkey.pem"


def _server_name_includes(server_name_value: str, domain: str) -> bool:
    names = server_name_value.strip().strip(";").split()
    return domain in names


def _find_server_block(lines: list[str], domain: str) -> tuple[int, int] | None:
    index = 0
    while index < len(lines):
        if SERVER_BLOCK_START.match(lines[index]):
            start = index
            depth = 0
            while index < len(lines):
                depth += lines[index].count("{") - lines[index].count("}")
                if depth <= 0:
                    block_lines = lines[start : index + 1]
                    for line in block_lines:
                        match = SERVER_NAME.match(line)
                        if match and _server_name_includes(match.group("names"), domain):
                            return start, index
                    break
                index += 1
        index += 1
    return None


def _block_indent(lines: list[str], start: int) -> str:
    for line in lines[start + 1 : start + 12]:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            return line[: len(line) - len(stripped)]
    return "    "


def _ssl_directives(domain: str, indent: str, live_dir: str) -> list[str]:
    fullchain, privkey = _cert_paths(domain, live_dir=live_dir)
    return [
        f"{indent}listen 443 ssl;",
        f"{indent}ssl_certificate {fullchain};",
        f"{indent}ssl_certificate_key {privkey};",
        f"{indent}include /etc/letsencrypt/options-ssl-nginx.conf;",
        f"{indent}ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;",
    ]


def patch_config_content(
    content: str,
    domain: str,
    *,
    live_dir: str = "/etc/letsencrypt/live",
) -> tuple[str, bool, str]:
    fullchain, privkey = _cert_paths(domain, live_dir=live_dir)
    if fullchain in content and privkey in content:
        return content, False, "nginx config already references the certificate paths"

    lines = content.splitlines()
    block = _find_server_block(lines, domain)
    if block is None:
        block = _find_server_block(lines, domain.split(".", 1)[-1]) if "." in domain else None
    if block is None:
        raise ValueError(f"no server block with server_name {domain} in config")

    start, end = block
    block_lines = lines[start : end + 1]
    indent = _block_indent(lines, start)

    if any(fullchain in line for line in block_lines):
        return content, False, "server block already has ssl_certificate configured"

    insert_at = end
    has_listen_443 = any(LISTEN_443.match(line) for line in block_lines)
    for offset, line in enumerate(block_lines):
        if line.strip().startswith("listen ") and "443" not in line:
            insert_at = start + offset + 1

    new_directives = _ssl_directives(domain, indent, live_dir=live_dir)
    if has_listen_443:
        new_directives = [line for line in new_directives if not line.strip().startswith("listen 443")]

    updated = lines[:insert_at] + new_directives + lines[insert_at:]
    return "\n".join(updated) + ("\n" if content.endswith("\n") else ""), True, "ssl directives added"


def _apply_ssl_sync(
    config_path: str,
    domain: str,
    *,
    live_dir: str,
    dry_run: bool,
) -> DeployResult:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"nginx config not found: {config_path}")

    original = path.read_text(encoding="utf-8", errors="replace")
    updated, changed, detail = patch_config_content(original, domain, live_dir=live_dir)
    if not changed:
        return DeployResult(changed=False, message=detail)

    if dry_run:
        return DeployResult(
            changed=True,
            message=f"dry-run: would update {config_path} ({detail})",
        )

    backup_path = f"{config_path}.iw.bak"
    shutil.copy2(config_path, backup_path)
    path.write_text(updated, encoding="utf-8")
    return DeployResult(
        changed=True,
        message=f"updated {config_path} ({detail})",
        backup_path=backup_path,
    )


async def apply_ssl_to_config(
    config_path: str,
    domain: str,
    *,
    live_dir: str = "/etc/letsencrypt/live",
    dry_run: bool = False,
) -> DeployResult:
    return await read(
        _apply_ssl_sync,
        config_path,
        domain,
        live_dir=live_dir,
        dry_run=dry_run,
    )


def _has_http_redirect(content: str, domain: str) -> bool:
    lines = content.splitlines()
    index = 0
    while index < len(lines):
        if SERVER_BLOCK_START.match(lines[index]):
            start = index
            depth = 0
            has_name = False
            has_redirect = False
            while index < len(lines):
                line = lines[index]
                depth += line.count("{") - line.count("}")
                match = SERVER_NAME.match(line)
                if match and _server_name_includes(match.group("names"), domain):
                    has_name = True
                if REDIRECT_RETURN.match(line):
                    has_redirect = True
                index += 1
                if depth <= 0:
                    if has_name and has_redirect:
                        return True
                    break
        index += 1
    return False


def patch_redirect_content(content: str, domain: str) -> tuple[str, bool, str]:
    if _has_http_redirect(content, domain):
        return content, False, "HTTP to HTTPS redirect already configured"

    lines = content.splitlines()
    block = _find_server_block(lines, domain)
    if block is None:
        raise ValueError(f"no server block with server_name {domain} in config")

    start, _end = block
    redirect_block = [
        "server {",
        "    listen 80;",
        "    listen [::]:80;",
        f"    server_name {domain};",
        "    return 301 https://$host$request_uri;",
        "}",
        "",
    ]
    updated = lines[:start] + redirect_block + lines[start:]
    trailing_newline = "\n" if content.endswith("\n") else ""
    return "\n".join(updated) + trailing_newline, True, "HTTP to HTTPS redirect added"


def _apply_redirect_sync(
    config_path: str,
    domain: str,
    *,
    dry_run: bool,
) -> DeployResult:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"nginx config not found: {config_path}")

    original = path.read_text(encoding="utf-8", errors="replace")
    updated, changed, detail = patch_redirect_content(original, domain)
    if not changed:
        return DeployResult(changed=False, message=detail)

    if dry_run:
        return DeployResult(
            changed=True,
            message=f"dry-run: would update {config_path} ({detail})",
        )

    backup_path = f"{config_path}.iw.bak"
    if not Path(backup_path).exists():
        shutil.copy2(config_path, backup_path)
    path.write_text(updated, encoding="utf-8")
    return DeployResult(
        changed=True,
        message=f"updated {config_path} ({detail})",
        backup_path=backup_path,
    )


async def apply_http_redirect_to_config(
    config_path: str,
    domain: str,
    *,
    dry_run: bool = False,
) -> DeployResult:
    return await read(
        _apply_redirect_sync,
        config_path,
        domain,
        dry_run=dry_run,
    )


def _remove_server_blocks(content: str, predicate) -> tuple[str, bool]:
    lines = content.splitlines()
    blocks = _extract_server_blocks(content)
    if not blocks:
        return content, False

    remove_ranges: list[tuple[int, int]] = []
    index = 0
    block_index = 0
    while index < len(lines) and block_index < len(blocks):
        if SERVER_BLOCK_START.match(lines[index]):
            block_lines = blocks[block_index]
            if predicate(block_lines):
                start = index
                depth = 0
                while index < len(lines):
                    depth += lines[index].count("{") - lines[index].count("}")
                    index += 1
                    if depth <= 0:
                        remove_ranges.append((start, index))
                        break
            else:
                depth = 0
                while index < len(lines):
                    depth += lines[index].count("{") - lines[index].count("}")
                    index += 1
                    if depth <= 0:
                        break
            block_index += 1
            continue
        index += 1

    if not remove_ranges:
        return content, False

    updated_lines = lines[:]
    for start, end in reversed(remove_ranges):
        del updated_lines[start:end]
    trailing_newline = "\n" if content.endswith("\n") else ""
    return "\n".join(updated_lines) + trailing_newline, True


def remove_http_redirect_content(content: str, domain: str) -> tuple[str, bool, str]:
    updated, changed = _remove_server_blocks(
        content,
        lambda block: _is_http_redirect_block(block, domain),
    )
    if not changed:
        return content, False, "HTTP to HTTPS redirect is not configured"
    return updated, True, "HTTP to HTTPS redirect removed"


def _has_www_redirect(content: str, domain: str) -> bool:
    return any(_is_www_redirect_block(block, domain) for block in _extract_server_blocks(content))


def patch_www_redirect_content(content: str, domain: str) -> tuple[str, bool, str]:
    if _has_www_redirect(content, domain):
        return content, False, "www redirect already configured"

    lines = content.splitlines()
    block = _find_server_block(lines, domain)
    if block is None:
        raise ValueError(f"no server block with server_name {domain} in config")

    start, _end = block
    redirect_block = [
        "server {",
        "    listen 80;",
        "    listen [::]:80;",
        f"    server_name www.{domain};",
        f"    return 301 https://{domain}$request_uri;",
        "}",
        "",
    ]
    updated = lines[:start] + redirect_block + lines[start:]
    trailing_newline = "\n" if content.endswith("\n") else ""
    return "\n".join(updated) + trailing_newline, True, "www to apex redirect added"


def remove_www_redirect_content(content: str, domain: str) -> tuple[str, bool, str]:
    updated, changed = _remove_server_blocks(
        content,
        lambda block: _is_www_redirect_block(block, domain),
    )
    if not changed:
        return content, False, "www redirect is not configured"
    return updated, True, "www redirect removed"


def apply_redirect_settings_content(
    content: str,
    domain: str,
    *,
    http_to_https: bool | None = None,
    www_to_apex: bool | None = None,
) -> tuple[str, bool, list[str]]:
    updated = content
    changed = False
    messages: list[str] = []

    if http_to_https is True:
        patched, block_changed, detail = patch_redirect_content(updated, domain)
        updated = patched
        if block_changed:
            changed = True
            messages.append(detail)
    elif http_to_https is False:
        patched, block_changed, detail = remove_http_redirect_content(updated, domain)
        updated = patched
        if block_changed:
            changed = True
            messages.append(detail)

    if www_to_apex is True:
        patched, block_changed, detail = patch_www_redirect_content(updated, domain)
        updated = patched
        if block_changed:
            changed = True
            messages.append(detail)
    elif www_to_apex is False:
        patched, block_changed, detail = remove_www_redirect_content(updated, domain)
        updated = patched
        if block_changed:
            changed = True
            messages.append(detail)

    if not changed:
        messages.append("no redirect changes needed")
    return updated, changed, messages


def _find_main_server_block(lines: list[str], domain: str) -> tuple[int, int] | None:
    index = 0
    while index < len(lines):
        if not SERVER_BLOCK_START.match(lines[index]):
            index += 1
            continue

        start = index
        depth = 0
        block_lines: list[str] = []
        while index < len(lines):
            line = lines[index]
            block_lines.append(line)
            depth += line.count("{") - line.count("}")
            index += 1
            if depth <= 0:
                if _is_http_redirect_block(block_lines, domain):
                    break
                if _is_www_redirect_block(block_lines, domain):
                    break
                for block_line in block_lines:
                    match = SERVER_NAME.match(block_line)
                    if match and _server_name_includes(match.group("names"), domain):
                        return start, index - 1
                break
    return None


def patch_backend_content(
    content: str,
    domain: str,
    *,
    proxy_pass: str | None = None,
    document_root: str | None = None,
    remove_proxy: bool = False,
    remove_root: bool = False,
) -> tuple[str, bool, str]:
    lines = content.splitlines()
    block = _find_main_server_block(lines, domain)
    if block is None:
        raise ValueError(f"no server block with server_name {domain} in config")

    start, end = block
    indent = _block_indent(lines, start)
    changed = False
    proxy_replaced = False
    root_replaced = False

    for index in range(start, end + 1):
        line = lines[index]
        proxy_match = PROXY_PASS_LINE.match(line)
        if proxy_match and (proxy_pass is not None or remove_proxy):
            if remove_proxy:
                lines[index] = ""
            else:
                lines[index] = f"{proxy_match.group(1)}proxy_pass {proxy_pass};"
            changed = True
            proxy_replaced = True
            continue
        root_match = ROOT_LINE.match(line)
        if root_match and (document_root is not None or remove_root):
            if remove_root:
                lines[index] = ""
            else:
                lines[index] = f"{root_match.group(1)}root {document_root};"
            changed = True
            root_replaced = True

    lines = [line for line in lines if line != ""]

    if proxy_pass is not None and not remove_proxy and not proxy_replaced:
        insert_at = end
        location_block = [
            f"{indent}location / {{",
            f"{indent}    proxy_pass {proxy_pass};",
            f"{indent}}}",
        ]
        lines = lines[:insert_at] + location_block + lines[insert_at:]
        changed = True

    if document_root is not None and not remove_root and not root_replaced:
        insert_at = end
        lines = lines[:insert_at] + [f"{indent}root {document_root};"] + lines[insert_at:]
        changed = True

    if not changed:
        return content, False, "no backend changes needed"

    trailing_newline = "\n" if content.endswith("\n") else ""
    detail_parts = []
    if proxy_pass is not None or remove_proxy:
        detail_parts.append("proxy_pass updated")
    if document_root is not None or remove_root:
        detail_parts.append("root updated")
    return "\n".join(lines) + trailing_newline, True, ", ".join(detail_parts)


def _apply_content_patch_sync(
    config_path: str,
    patch_fn,
    *,
    dry_run: bool,
) -> DeployResult:
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"nginx config not found: {config_path}")

    original = path.read_text(encoding="utf-8", errors="replace")
    updated, changed, detail = patch_fn(original)
    if not changed:
        message = detail if isinstance(detail, str) else "; ".join(detail)
        return DeployResult(changed=False, message=message)

    message = detail if isinstance(detail, str) else "; ".join(detail)
    if dry_run:
        return DeployResult(changed=True, message=f"dry-run: would update {config_path} ({message})")

    backup_path = f"{config_path}.iw.bak"
    if not Path(backup_path).exists():
        shutil.copy2(config_path, backup_path)
    path.write_text(updated, encoding="utf-8")
    return DeployResult(
        changed=True,
        message=f"updated {config_path} ({message})",
        backup_path=backup_path,
    )


async def apply_redirect_settings_to_config(
    config_path: str,
    domain: str,
    *,
    http_to_https: bool | None = None,
    www_to_apex: bool | None = None,
    dry_run: bool = False,
) -> DeployResult:
    def _patch(content: str) -> tuple[str, bool, list[str] | str]:
        return apply_redirect_settings_content(
            content,
            domain,
            http_to_https=http_to_https,
            www_to_apex=www_to_apex,
        )

    return await read(
        _apply_content_patch_sync,
        config_path,
        _patch,
        dry_run=dry_run,
    )


def _format_security_header_line(indent: str, name: str, value: str) -> str:
    return f'{indent}add_header {name} "{value}" always;'


def patch_security_preset_content(
    content: str,
    domain: str,
    preset: SecurityPreset,
) -> tuple[str, bool, str]:
    lines = content.splitlines()
    block = _find_main_server_block(lines, domain)
    if block is None:
        raise ValueError(f"no server block with server_name {domain} in config")

    start, end = block
    indent = _block_indent(lines, start)
    current_headers: dict[str, str] = {}
    for line in lines[start : end + 1]:
        match = ADD_HEADER_LINE.match(line)
        if match and match.group("name") in MANAGED_SECURITY_HEADER_NAMES:
            current_headers[match.group("name")] = match.group("value")

    desired = dict(security_headers_for_preset(preset))
    if current_headers == desired:
        return content, False, f"security preset already {preset.value}"

    block_lines: list[str] = []
    for line in lines[start : end + 1]:
        match = ADD_HEADER_LINE.match(line)
        if match and match.group("name") in MANAGED_SECURITY_HEADER_NAMES:
            continue
        block_lines.append(line)

    if desired:
        closing_index = len(block_lines) - 1
        header_lines = [
            _format_security_header_line(indent, name, value) for name, value in desired.items()
        ]
        block_lines = block_lines[:closing_index] + header_lines + block_lines[closing_index:]

    updated_lines = lines[:start] + block_lines + lines[end + 1 :]
    trailing_newline = "\n" if content.endswith("\n") else ""
    if preset is SecurityPreset.NONE:
        detail = "removed managed security headers"
    else:
        detail = f"applied {preset.value} security preset"
    return "\n".join(updated_lines) + trailing_newline, True, detail


def _find_location_root_in_block(lines: list[str], start: int, end: int) -> tuple[int, int] | None:
    index = start + 1
    while index <= end:
        if LOCATION_ROOT_START.match(lines[index]):
            loc_start = index
            depth = 0
            while index <= end:
                depth += lines[index].count("{") - lines[index].count("}")
                index += 1
                if depth <= 0:
                    return loc_start, index - 1
            return None
        index += 1
    return None


def _static_patch_range(
    lines: list[str],
    server_start: int,
    server_end: int,
) -> tuple[int, int, str, str]:
    server_indent = _block_indent(lines, server_start)
    location = _find_location_root_in_block(lines, server_start, server_end)
    if location is not None:
        loc_start, loc_end = location
        block_text = "\n".join(lines[loc_start : loc_end + 1])
        if "proxy_pass" not in block_text:
            inner_indent = _block_indent(lines, loc_start)
            return loc_start, loc_end, inner_indent, server_indent
    return server_start, server_end, server_indent, server_indent


def _remove_line_indices(lines: list[str], indices: set[int]) -> None:
    for index in sorted(indices, reverse=True):
        del lines[index]


def patch_static_content(
    content: str,
    domain: str,
    *,
    document_root: str | None = None,
    index_files: str | None = None,
    try_files: str | None = None,
    remove_root: bool = False,
    remove_index: bool = False,
    remove_try_files: bool = False,
) -> tuple[str, bool, str]:
    lines = content.splitlines()
    block = _find_main_server_block(lines, domain)
    if block is None:
        raise ValueError(f"no server block with server_name {domain} in config")

    start, end = block
    target_start, target_end, target_indent, server_indent = _static_patch_range(lines, start, end)
    changed = False
    root_replaced = index_replaced = try_files_replaced = False
    remove_indices: set[int] = set()

    for index in range(start, end + 1):
        root_match = ROOT_LINE.match(lines[index])
        if root_match and (document_root is not None or remove_root):
            if remove_root:
                remove_indices.add(index)
            else:
                lines[index] = f"{root_match.group(1)}root {document_root};"
            changed = True
            root_replaced = True
            break

    for index in range(target_start, target_end + 1):
        index_match = INDEX_LINE.match(lines[index])
        if index_match and (index_files is not None or remove_index):
            if remove_index:
                remove_indices.add(index)
            else:
                lines[index] = f"{index_match.group(1)}index {index_files};"
            changed = True
            index_replaced = True
            continue
        try_match = TRY_FILES_LINE.match(lines[index])
        if try_match and (try_files is not None or remove_try_files):
            if remove_try_files:
                remove_indices.add(index)
            else:
                lines[index] = f"{try_match.group(1)}try_files {try_files};"
            changed = True
            try_files_replaced = True

    if remove_indices:
        _remove_line_indices(lines, remove_indices)
        block = _find_main_server_block(lines, domain)
        if block is None:
            raise ValueError(f"no server block with server_name {domain} in config")
        start, end = block
        target_start, target_end, target_indent, server_indent = _static_patch_range(lines, start, end)

    if document_root is not None and not remove_root and not root_replaced:
        lines = lines[:end] + [f"{server_indent}root {document_root};"] + lines[end:]
        changed = True
        block = _find_main_server_block(lines, domain)
        if block is None:
            raise ValueError(f"no server block with server_name {domain} in config")
        start, end = block
        target_start, target_end, target_indent, server_indent = _static_patch_range(lines, start, end)

    if index_files is not None and not remove_index and not index_replaced:
        lines = lines[:target_end] + [f"{target_indent}index {index_files};"] + lines[target_end:]
        changed = True
        block = _find_main_server_block(lines, domain)
        if block is None:
            raise ValueError(f"no server block with server_name {domain} in config")
        start, end = block
        target_start, target_end, target_indent, server_indent = _static_patch_range(lines, start, end)

    if try_files is not None and not remove_try_files and not try_files_replaced:
        location = _find_location_root_in_block(lines, start, end)
        if location is None:
            location_block = [
                f"{server_indent}location / {{",
                f"{server_indent}    try_files {try_files};",
                f"{server_indent}}}",
            ]
            lines = lines[:end] + location_block + lines[end:]
        else:
            lines = lines[:target_end] + [f"{target_indent}try_files {try_files};"] + lines[target_end:]
        changed = True

    if not changed:
        return content, False, "no static file changes needed"

    trailing_newline = "\n" if content.endswith("\n") else ""
    detail_parts = []
    if document_root is not None or remove_root:
        detail_parts.append("root updated")
    if index_files is not None or remove_index:
        detail_parts.append("index updated")
    if try_files is not None or remove_try_files:
        detail_parts.append("try_files updated")
    return "\n".join(lines) + trailing_newline, True, ", ".join(detail_parts)


def generate_site_config(
    domain: str,
    *,
    site_kind: SiteKind,
    document_root: str | None = None,
    index_files: str = DEFAULT_INDEX_FILES,
    try_files: str = TRY_FILES_STANDARD,
    proxy_pass: str | None = None,
) -> str:
    lines = [
        "# Created by InfraWatch",
        "server {",
        "    listen 80;",
        "    listen [::]:80;",
        f"    server_name {domain};",
        "",
    ]

    if site_kind is SiteKind.STATIC:
        root = document_root or f"/var/www/{domain}"
        lines.extend(
            [
                f"    root {root};",
                f"    index {index_files};",
                "",
                "    location / {",
                f"        try_files {try_files};",
                "    }",
            ],
        )
    elif site_kind is SiteKind.PROXY:
        if not proxy_pass:
            raise ValueError("proxy_pass is required for proxy sites")
        lines.extend(
            [
                "    location / {",
                f"        proxy_pass {proxy_pass};",
                "        proxy_set_header Host $host;",
                "        proxy_set_header X-Real-IP $remote_addr;",
                "        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                "        proxy_set_header X-Forwarded-Proto $scheme;",
                "    }",
            ],
        )
    else:
        raise ValueError(f"unknown site kind: {site_kind}")

    lines.extend(["}", ""])
    return "\n".join(lines)


def _create_site_sync(
    config: NginxExecutorConfig,
    *,
    domain: str,
    site_kind: SiteKind,
    document_root: str | None,
    index_files: str,
    try_files: str,
    proxy_pass: str | None,
    enable_site: bool,
    dry_run: bool,
) -> DeployResult:
    if not domain:
        raise ValueError("domain is required")

    config_path = os.path.join(config.sites_available_dir, domain)
    if Path(config_path).exists():
        raise ValueError(f"config already exists: {config_path}")

    content = generate_site_config(
        domain,
        site_kind=site_kind,
        document_root=document_root,
        index_files=index_files,
        try_files=try_files,
        proxy_pass=proxy_pass,
    )

    if dry_run:
        parts = [f"dry-run: would create {config_path}"]
        if enable_site:
            link_name = os.path.join(config.sites_enabled_dir, domain)
            parts.append(f"would enable via {link_name}")
        return DeployResult(changed=True, message=" · ".join(parts))

    sites_available = Path(config.sites_available_dir)
    if not sites_available.is_dir():
        raise FileNotFoundError(f"sites-available directory not found: {config.sites_available_dir}")

    sites_available.joinpath(domain).write_text(content, encoding="utf-8")

    message = f"created {config_path}"
    if enable_site:
        sites_enabled = Path(config.sites_enabled_dir)
        if not sites_enabled.is_dir():
            raise FileNotFoundError(f"sites-enabled directory not found: {config.sites_enabled_dir}")
        link_name = sites_enabled / domain
        link_name.symlink_to(os.path.realpath(config_path))
        message = f"{message} · enabled ({link_name})"

    return DeployResult(changed=True, message=message)


async def create_site_on_disk(
    config: NginxExecutorConfig,
    *,
    domain: str,
    site_kind: SiteKind,
    document_root: str | None = None,
    index_files: str = DEFAULT_INDEX_FILES,
    try_files: str = TRY_FILES_STANDARD,
    proxy_pass: str | None = None,
    enable_site: bool = True,
    dry_run: bool = False,
) -> DeployResult:
    return await read(
        _create_site_sync,
        config,
        domain=domain,
        site_kind=site_kind,
        document_root=document_root,
        index_files=index_files,
        try_files=try_files,
        proxy_pass=proxy_pass,
        enable_site=enable_site,
        dry_run=dry_run,
    )


async def apply_static_settings_to_config(
    config_path: str,
    domain: str,
    *,
    document_root: str | None = None,
    index_files: str | None = None,
    try_files: str | None = None,
    remove_root: bool = False,
    remove_index: bool = False,
    remove_try_files: bool = False,
    dry_run: bool = False,
) -> DeployResult:
    def _patch(content: str) -> tuple[str, bool, str]:
        return patch_static_content(
            content,
            domain,
            document_root=document_root,
            index_files=index_files,
            try_files=try_files,
            remove_root=remove_root,
            remove_index=remove_index,
            remove_try_files=remove_try_files,
        )

    return await read(
        _apply_content_patch_sync,
        config_path,
        _patch,
        dry_run=dry_run,
    )


async def apply_security_settings_to_config(
    config_path: str,
    domain: str,
    *,
    preset: SecurityPreset,
    dry_run: bool = False,
) -> DeployResult:
    def _patch(content: str) -> tuple[str, bool, str]:
        return patch_security_preset_content(content, domain, preset)

    return await read(
        _apply_content_patch_sync,
        config_path,
        _patch,
        dry_run=dry_run,
    )


async def apply_backend_settings_to_config(
    config_path: str,
    domain: str,
    *,
    proxy_pass: str | None = None,
    document_root: str | None = None,
    remove_proxy: bool = False,
    remove_root: bool = False,
    dry_run: bool = False,
) -> DeployResult:
    def _patch(content: str) -> tuple[str, bool, str]:
        return patch_backend_content(
            content,
            domain,
            proxy_pass=proxy_pass,
            document_root=document_root,
            remove_proxy=remove_proxy,
            remove_root=remove_root,
        )

    return await read(
        _apply_content_patch_sync,
        config_path,
        _patch,
        dry_run=dry_run,
    )


@dataclass(frozen=True)
class NginxExecutorConfig:
    nginx_binary: str = DEFAULT_NGINX_BINARY
    timeout: float = DEFAULT_NGINX_TIMEOUT_SECONDS
    sites_available_dir: str = DEFAULT_SITES_AVAILABLE_DIR
    sites_enabled_dir: str = DEFAULT_SITES_ENABLED_DIR
    certbot_binary: str = "certbot"
    certbot_timeout: float = 120.0
    certbot_live_dir: str = "/etc/letsencrypt/live"
    webroot: str = "/var/www/html"

    @classmethod
    def from_params(cls, params: dict) -> NginxExecutorConfig:
        values = {
            key: params[key]
            for key in (
                "nginx_binary",
                "timeout",
                "sites_available_dir",
                "sites_enabled_dir",
                "certbot_binary",
                "certbot_timeout",
                "certbot_live_dir",
                "webroot",
            )
            if key in params
        }
        return cls(**values)


class NginxExecutor:
    module = MODULE

    def actions(self):
        return NGINX_SITE_ACTIONS

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        spec = NGINX_ACTIONS_BY_ID.get(request.action_id)
        if spec is None:
            return _fail(request, f"unknown nginx action: {request.action_id}", options)

        handler = _HANDLERS.get(request.action_id)
        if handler is None:
            return _fail(request, f"handler missing for {request.action_id}", options)

        config = NginxExecutorConfig.from_params(request.params)
        virtual_host = await _resolve_virtual_host(request, config)
        if virtual_host is None and request.action_id not in {
            "reload",
            "attach_ssl",
            "apply_redirect_settings",
            "apply_backend_settings",
            "apply_security_settings",
            "apply_static_settings",
            "create_site",
        }:
            return _fail(
                request,
                f"virtual host not found for target {request.target_id!r}",
                options,
            )

        return await handler(request, options, virtual_host=virtual_host, config=config)


async def _resolve_virtual_host(
    request: ActionRequest,
    config: NginxExecutorConfig,
) -> VirtualHost | None:
    embedded = request.params.get("virtual_host")
    if embedded is not None:
        return VirtualHost.model_validate(embedded)

    if not request.target_id:
        return None

    target_path = os.path.realpath(request.target_id)
    virtual_hosts = await collect_virtual_hosts(
        nginx_binary=config.nginx_binary,
        timeout=config.timeout,
    )
    for virtual_host in virtual_hosts:
        if virtual_host.config_path and os.path.realpath(virtual_host.config_path) == target_path:
            return virtual_host
    return None


def _domain_for(virtual_host: VirtualHost, params: dict) -> str | None:
    domain = params.get("domain")
    if domain:
        return str(domain)
    if virtual_host.server_names:
        return virtual_host.server_names[0]
    return None


def _fail(request: ActionRequest, message: str, options: ExecutorOptions) -> ActionResult:
    return ActionResult(
        ok=False,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


async def _view_details(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    names = ", ".join(virtual_host.server_names) or "-"
    ports = ", ".join(str(port) for port in virtual_host.listen_ports) or "-"
    lines = [
        f"server_names={names}",
        f"enabled={virtual_host.enabled}",
        f"config_path={virtual_host.config_path or '-'}",
        f"listen_ports={ports}",
        f"ssl_enabled={virtual_host.ssl_enabled}",
    ]
    if virtual_host.upstream:
        lines.append(f"upstream={virtual_host.upstream}")
    if virtual_host.cert_path:
        lines.append(f"cert_path={virtual_host.cert_path}")
    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message="\n".join(lines),
        dry_run=False,
    )


async def _test_config(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    argv = [config.nginx_binary, "-t"]
    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(argv)}",
            dry_run=True,
        )

    result = await run_command(argv, timeout=config.timeout)
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message="nginx config test passed" if result.ok else "nginx config test failed",
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _reload(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    test_result = await _test_config(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
    )
    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message="dry-run: would run nginx -t, then reload nginx",
            dry_run=True,
        )
    if not test_result.ok:
        return ActionResult(
            ok=False,
            module=MODULE,
            action_id=request.action_id,
            message="reload aborted — nginx config test failed",
            stdout=test_result.stdout,
            stderr=test_result.stderr,
        )

    reload_argv = _reload_argv(config.nginx_binary)
    result = await run_command(reload_argv, timeout=config.timeout)
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message="nginx reloaded" if result.ok else "nginx reload failed",
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _enable_site(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)
    if virtual_host.enabled:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message="site is already enabled",
        )

    source = os.path.realpath(virtual_host.config_path)
    link_name = os.path.join(config.sites_enabled_dir, os.path.basename(source))
    command = ["ln", "-sf", source, link_name]
    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(command)}",
            dry_run=True,
        )

    result = await run_command(command, timeout=config.timeout)
    if not result.ok:
        return ActionResult(
            ok=False,
            module=MODULE,
            action_id=request.action_id,
            message="failed to enable site",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    reload_result = await _reload(request, options, virtual_host=virtual_host, config=config)
    if reload_result.ok:
        reload_result = reload_result.model_copy(
            update={"message": f"site enabled and nginx reloaded ({link_name})"},
        )
    return reload_result


async def _disable_site(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)
    if not virtual_host.enabled:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message="site is already disabled",
        )

    link_name = os.path.join(config.sites_enabled_dir, os.path.basename(virtual_host.config_path))
    command = ["rm", "-f", link_name]
    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(command)}",
            dry_run=True,
        )

    if not Path(link_name).exists():
        return ActionResult(
            ok=False,
            module=MODULE,
            action_id=request.action_id,
            message=f"enabled symlink not found: {link_name}",
        )

    result = await run_command(command, timeout=config.timeout)
    if not result.ok:
        return ActionResult(
            ok=False,
            module=MODULE,
            action_id=request.action_id,
            message="failed to disable site",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    reload_result = await _reload(request, options, virtual_host=virtual_host, config=config)
    if reload_result.ok:
        reload_result = reload_result.model_copy(
            update={"message": f"site disabled and nginx reloaded ({link_name})"},
        )
    return reload_result


async def _attach_ssl(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    config_path = request.target_id or (virtual_host.config_path if virtual_host else None)
    domain = request.params.get("domain")
    if not config_path:
        return _fail(request, "target_id (config path) is required", options)
    if not domain:
        if virtual_host and virtual_host.server_names:
            domain = virtual_host.server_names[0]
        else:
            return _fail(request, "domain is required in params", options)

    live_dir = str(request.params.get("certbot_live_dir", config.certbot_live_dir))
    try:
        deploy_result = await apply_ssl_to_config(
            config_path,
            str(domain),
            live_dir=live_dir,
            dry_run=options.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(request, str(exc), options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=deploy_result.message,
        dry_run=options.dry_run and deploy_result.changed,
    )


async def _secure_site(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    domain = _domain_for(virtual_host, request.params)
    email = request.params.get("email")
    if not domain:
        return _fail(request, "domain is required (server_name missing)", options)
    if not email:
        return _fail(request, "email is required in params for Let's Encrypt", options)

    errors, warnings = await precheck_certificate_domain(domain)
    precheck_notes = errors + warnings
    if errors and not request.params.get("force"):
        return _fail(request, "precheck failed: " + "; ".join(errors), options)

    service = get_action_service()
    nginx_params = {
        "nginx_binary": config.nginx_binary,
        "timeout": config.timeout,
        "certbot_live_dir": config.certbot_live_dir,
    }
    skip_redirect = bool(request.params.get("skip_redirect", False))

    if options.dry_run:
        certbot_request = CertbotRequest(
            domain=domain,
            email=str(email),
            method=str(request.params.get("method", "auto")),
            webroot=str(request.params.get("webroot", config.webroot)),
            staging=bool(request.params.get("staging", False)),
            certbot_binary=config.certbot_binary,
            timeout=config.certbot_timeout,
        )
        argv, _ = await obtain_certificate(certbot_request, dry_run=True)
        redirect_note = "" if skip_redirect else "\nthen add HTTP→HTTPS redirect"
        precheck_line = f"\nprecheck: {'; '.join(precheck_notes)}" if precheck_notes else ""
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=(
                f"dry-run: would run {' '.join(argv)}\n"
                f"then attach ssl to {virtual_host.config_path}{redirect_note} and reload nginx"
                f"{precheck_line}"
            ),
            dry_run=True,
        )

    obtain_result = await service.run(
        ActionRequest(
            module="ssl",
            action_id="obtain_certificate",
            target_id=domain,
            params={
                "domain": domain,
                "email": email,
                "method": request.params.get("method", "auto"),
                "webroot": request.params.get("webroot", config.webroot),
                "staging": request.params.get("staging", False),
                "certbot_binary": config.certbot_binary,
                "certbot_timeout": config.certbot_timeout,
                "certbot_live_dir": config.certbot_live_dir,
            },
        ),
        options=ExecutorOptions(
            dry_run=False,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )
    if not obtain_result.ok:
        return obtain_result.model_copy(update={"module": MODULE, "action_id": request.action_id})

    attach_result = await service.run(
        ActionRequest(
            module=MODULE,
            action_id="attach_ssl",
            target_id=virtual_host.config_path,
            params={**nginx_params, "domain": domain},
        ),
        options=ExecutorOptions(
            dry_run=False,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )
    if not attach_result.ok:
        return attach_result.model_copy(update={"module": MODULE, "action_id": request.action_id})

    redirect_message = ""
    if not skip_redirect:
        try:
            redirect_result = await apply_http_redirect_to_config(
                virtual_host.config_path,
                domain,
                dry_run=False,
            )
            redirect_message = redirect_result.message
        except (FileNotFoundError, ValueError) as exc:
            return _fail(request, str(exc), options)

    reload_result = await service.run(
        ActionRequest(
            module=MODULE,
            action_id="reload",
            target_id=virtual_host.config_path,
            params=nginx_params,
        ),
        options=ExecutorOptions(
            dry_run=False,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )
    if not reload_result.ok:
        return reload_result.model_copy(update={"module": MODULE, "action_id": request.action_id})

    message = f"HTTPS enabled for {domain}"
    if redirect_message:
        message = f"{message} · {redirect_message}"

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        stdout="\n".join(
            part
            for part in (obtain_result.stdout, attach_result.stdout, reload_result.stdout)
            if part.strip()
        ),
        stderr="\n".join(
            part
            for part in (obtain_result.stderr, attach_result.stderr, reload_result.stderr)
            if part.strip()
        ),
    )


async def _renew_site(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    domain = _domain_for(virtual_host, request.params)
    if not domain:
        return _fail(request, "domain is required (server_name missing)", options)

    service = get_action_service()
    nginx_params = {
        "nginx_binary": config.nginx_binary,
        "timeout": config.timeout,
    }

    if options.dry_run:
        argv, _ = await renew_certificate(
            domain,
            certbot_binary=config.certbot_binary,
            timeout=config.certbot_timeout,
            staging=bool(request.params.get("staging", False)),
            dry_run=True,
        )
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(argv)} then reload nginx",
            dry_run=True,
        )

    renew_result = await service.run(
        ActionRequest(
            module="ssl",
            action_id="renew_certificate",
            target_id=domain,
            params={
                "cert_name": domain,
                "certbot_binary": config.certbot_binary,
                "certbot_timeout": config.certbot_timeout,
                "staging": request.params.get("staging", False),
            },
        ),
        options=ExecutorOptions(
            dry_run=False,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )
    if not renew_result.ok:
        return renew_result.model_copy(update={"module": MODULE, "action_id": request.action_id})

    reload_result = await service.run(
        ActionRequest(
            module=MODULE,
            action_id="reload",
            target_id=virtual_host.config_path,
            params=nginx_params,
        ),
        options=ExecutorOptions(
            dry_run=False,
            skip_confirm=True,
            audit_log_path=options.audit_log_path,
        ),
    )
    if not reload_result.ok:
        return reload_result.model_copy(update={"module": MODULE, "action_id": request.action_id})

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=f"certificate renewed for {domain}",
        stdout="\n".join(
            part for part in (renew_result.stdout, reload_result.stdout) if part.strip()
        ),
        stderr="\n".join(
            part for part in (renew_result.stderr, reload_result.stderr) if part.strip()
        ),
    )


async def _maybe_reload_after_config_change(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost,
    config: NginxExecutorConfig,
    message: str,
) -> ActionResult:
    if options.dry_run or not request.params.get("reload", True):
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=message,
            dry_run=options.dry_run,
        )

    reload_result = await _reload(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
    )
    if not reload_result.ok:
        return ActionResult(
            ok=False,
            module=MODULE,
            action_id=request.action_id,
            message=f"{message} · reload failed",
            stdout=reload_result.stdout,
            stderr=reload_result.stderr,
        )
    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=f"{message} · nginx reloaded",
        stdout=reload_result.stdout,
        stderr=reload_result.stderr,
    )


async def _apply_redirect_settings(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    domain = _domain_for(virtual_host, request.params)
    if not domain:
        return _fail(request, "domain is required (server_name missing)", options)

    params = request.params
    if "http_to_https" not in params and "www_to_apex" not in params:
        return _fail(request, "http_to_https or www_to_apex is required in params", options)

    http_value = params.get("http_to_https")
    www_value = params.get("www_to_apex")
    try:
        deploy_result = await apply_redirect_settings_to_config(
            virtual_host.config_path,
            domain,
            http_to_https=http_value if "http_to_https" in params else None,
            www_to_apex=www_value if "www_to_apex" in params else None,
            dry_run=options.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(request, str(exc), options)

    return await _maybe_reload_after_config_change(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
        message=deploy_result.message,
    )


async def _apply_security_settings(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    domain = _domain_for(virtual_host, request.params)
    if not domain:
        return _fail(request, "domain is required (server_name missing)", options)

    preset_value = request.params.get("security_preset")
    if not preset_value:
        return _fail(request, "security_preset is required in params", options)

    try:
        preset = SecurityPreset(preset_value)
    except ValueError:
        return _fail(request, f"unknown security preset: {preset_value}", options)

    if preset is SecurityPreset.STRICT and not virtual_host.ssl_enabled:
        return _fail(
            request,
            "Strict preset requires HTTPS — obtain a certificate first",
            options,
        )

    try:
        deploy_result = await apply_security_settings_to_config(
            virtual_host.config_path,
            domain,
            preset=preset,
            dry_run=options.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(request, str(exc), options)

    return await _maybe_reload_after_config_change(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
        message=deploy_result.message,
    )


async def _apply_static_settings(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    domain = _domain_for(virtual_host, request.params)
    if not domain:
        return _fail(request, "domain is required (server_name missing)", options)

    params = request.params
    if not any(
        key in params
        for key in (
            "document_root",
            "index_files",
            "try_files",
            "remove_root",
            "remove_index",
            "remove_try_files",
        )
    ):
        return _fail(
            request,
            "document_root, index_files, try_files, or a remove_* flag is required",
            options,
        )

    try:
        deploy_result = await apply_static_settings_to_config(
            virtual_host.config_path,
            domain,
            document_root=params.get("document_root"),
            index_files=params.get("index_files"),
            try_files=params.get("try_files"),
            remove_root=bool(params.get("remove_root", False)),
            remove_index=bool(params.get("remove_index", False)),
            remove_try_files=bool(params.get("remove_try_files", False)),
            dry_run=options.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(request, str(exc), options)

    return await _maybe_reload_after_config_change(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
        message=deploy_result.message,
    )


async def _create_site(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    params = request.params
    domain = params.get("domain")
    if not domain:
        return _fail(request, "domain is required in params", options)

    site_kind_value = params.get("site_kind", SiteKind.STATIC.value)
    try:
        site_kind = SiteKind(site_kind_value)
    except ValueError:
        return _fail(request, f"unknown site kind: {site_kind_value}", options)

    proxy_pass = params.get("proxy_pass")
    if site_kind is SiteKind.PROXY and not proxy_pass:
        return _fail(request, "proxy_pass is required for proxy sites", options)

    enable_site = bool(params.get("enable_site", True))
    try:
        deploy_result = await create_site_on_disk(
            config,
            domain=str(domain),
            site_kind=site_kind,
            document_root=params.get("document_root"),
            index_files=str(params.get("index_files", DEFAULT_INDEX_FILES)),
            try_files=str(params.get("try_files", TRY_FILES_STANDARD)),
            proxy_pass=proxy_pass,
            enable_site=enable_site,
            dry_run=options.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(request, str(exc), options)

    if options.dry_run or not enable_site or not request.params.get("reload", True):
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=deploy_result.message,
            dry_run=options.dry_run,
        )

    reload_result = await _reload(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
    )
    if not reload_result.ok:
        return ActionResult(
            ok=False,
            module=MODULE,
            action_id=request.action_id,
            message=f"{deploy_result.message} · reload failed",
            stdout=reload_result.stdout,
            stderr=reload_result.stderr,
        )
    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=f"{deploy_result.message} · nginx reloaded",
        stdout=reload_result.stdout,
        stderr=reload_result.stderr,
    )


async def _apply_backend_settings(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    virtual_host: VirtualHost | None,
    config: NginxExecutorConfig,
) -> ActionResult:
    if virtual_host is None:
        return _fail(request, "virtual host is required", options)

    domain = _domain_for(virtual_host, request.params)
    if not domain:
        return _fail(request, "domain is required (server_name missing)", options)

    params = request.params
    try:
        deploy_result = await apply_backend_settings_to_config(
            virtual_host.config_path,
            domain,
            proxy_pass=params.get("proxy_pass"),
            document_root=params.get("document_root"),
            remove_proxy=bool(params.get("remove_proxy", False)),
            remove_root=bool(params.get("remove_root", False)),
            dry_run=options.dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        return _fail(request, str(exc), options)

    return await _maybe_reload_after_config_change(
        request,
        options,
        virtual_host=virtual_host,
        config=config,
        message=deploy_result.message,
    )


def _reload_argv(nginx_binary: str) -> list[str]:
    if is_command_available("systemctl"):
        return ["systemctl", "reload", "nginx"]
    return [nginx_binary, "-s", "reload"]


_HANDLERS = {
    "view_details": _view_details,
    "test_config": _test_config,
    "reload": _reload,
    "enable_site": _enable_site,
    "disable_site": _disable_site,
    "attach_ssl": _attach_ssl,
    "secure_site": _secure_site,
    "renew_site": _renew_site,
    "apply_redirect_settings": _apply_redirect_settings,
    "apply_backend_settings": _apply_backend_settings,
    "apply_security_settings": _apply_security_settings,
    "apply_static_settings": _apply_static_settings,
    "create_site": _create_site,
}
