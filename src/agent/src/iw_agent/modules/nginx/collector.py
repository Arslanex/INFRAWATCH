from __future__ import annotations

import os
import re
from pathlib import Path

from iw_agent.core.commands import CommandResult, is_command_available, run_command
from iw_agent.core.exceptions import (
    NginxCommandFailedError,
    NginxCommandStartError,
    NginxNotInstalledError,
    NginxTimeoutError,
)
from iw_agent.core.logger import logger
from iw_agent.modules.nginx.schemas import (
    ListenEndpoint,
    LocationBlock,
    SiteProfile,
    SslStatus,
    VirtualHost,
)
from iw_agent.modules.ssl.collector import DEFAULT_CERTBOT_LIVE_DIR, collect_certificates
from iw_agent.modules.ssl.schemas import Certificate

CONFIG_FILE_MARKER = re.compile(r"^#\s*configuration file (?P<path>.+):$")
SERVER_BLOCK_START = re.compile(r"^\s*server\s*\{")
DIRECTIVE_PATTERN = re.compile(r"(?P<name>[a-z_]+)\s+(?P<value>[^;{}]+);")

DEFAULT_NGINX_BINARY = "nginx"
DEFAULT_NGINX_TIMEOUT_SECONDS = 30.0
DEFAULT_SITES_AVAILABLE_DIR = "/etc/nginx/sites-available"
DEFAULT_SITES_ENABLED_DIR = "/etc/nginx/sites-enabled"
MAX_PARSE_ERROR_LENGTH = 2000
MAX_RAW_CONFIG_LENGTH = 100_000


async def fetch_nginx_dump(
    nginx_binary: str = DEFAULT_NGINX_BINARY,
    timeout: float = DEFAULT_NGINX_TIMEOUT_SECONDS,
) -> CommandResult | None:
    # 1. Binary yoksa None dön
    if not is_command_available(nginx_binary):
        logger.debug("%s", NginxNotInstalledError())
        return None

    # 2. nginx -T çalıştır (ssl collector aynı dump'ı kullanabilir)
    try:
        return await run_command([nginx_binary, "-T"], timeout=timeout)
    except OSError as exc:
        logger.debug("%s", NginxCommandStartError(f"nginx -T could not start: {exc}"))
        return None


async def collect_virtual_hosts(
    nginx_binary: str = DEFAULT_NGINX_BINARY,
    timeout: float = DEFAULT_NGINX_TIMEOUT_SECONDS,
) -> list[VirtualHost]:
    dump_result = await fetch_nginx_dump(
        nginx_binary=nginx_binary,
        timeout=timeout,
    )
    if dump_result is None:
        return []

    # 3. Komut başarısız → parse_ok=False satırı (tick kırılmaz, TR-01)
    if not dump_result.ok:
        if dump_result.timed_out:
            logger.warning("%s", NginxTimeoutError(f"nginx -T timed out after {timeout:.1f}s"))
        else:
            logger.warning(
                "%s",
                NginxCommandFailedError(
                    f"nginx -T failed (exit {dump_result.exit_code})"
                ),
            )
        return [_unparsed_virtual_host_from_command_failure(dump_result, timeout)]

    # 4. Dump'ı parse et (nginx -T = aktif config)
    active_hosts = parse_nginx_dump(dump_result.stdout)
    for virtual_host in active_hosts:
        virtual_host.enabled = True

    disabled_hosts = _collect_disabled_virtual_hosts()
    active_paths = {
        os.path.realpath(host.config_path)
        for host in active_hosts
        if host.config_path and host.parse_ok
    }
    merged_hosts = active_hosts + [
        host
        for host in disabled_hosts
        if os.path.realpath(host.config_path) not in active_paths
    ]
    logger.debug(
        "collected %d nginx virtual hosts (%d active, %d disabled)",
        len(merged_hosts),
        len(active_hosts),
        len(merged_hosts) - len(active_hosts),
    )
    return merged_hosts


def parse_nginx_config_file(config_path: str, content: str) -> list[VirtualHost]:
    return parse_nginx_dump(f"# configuration file {config_path}:\n{content}")


def _collect_disabled_virtual_hosts(
    sites_available_dir: str = DEFAULT_SITES_AVAILABLE_DIR,
    sites_enabled_dir: str = DEFAULT_SITES_ENABLED_DIR,
) -> list[VirtualHost]:
    if not os.path.isdir(sites_available_dir):
        return []

    enabled_paths = _enabled_site_realpaths(sites_enabled_dir)
    disabled_hosts: list[VirtualHost] = []

    for entry in sorted(os.listdir(sites_available_dir)):
        if entry.startswith("."):
            continue

        config_path = os.path.join(sites_available_dir, entry)
        if not os.path.isfile(config_path):
            continue

        if os.path.realpath(config_path) in enabled_paths:
            continue

        try:
            content = Path(config_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("could not read disabled nginx config %s: %s", config_path, exc)
            disabled_hosts.append(
                VirtualHost(
                    config_path=config_path,
                    enabled=False,
                    parse_ok=False,
                    parse_error=f"could not read config file: {exc}",
                )
            )
            continue

        for virtual_host in parse_nginx_config_file(config_path, content):
            virtual_host.enabled = False
            disabled_hosts.append(virtual_host)

    return disabled_hosts


def _enabled_site_realpaths(sites_enabled_dir: str) -> set[str]:
    if not os.path.isdir(sites_enabled_dir):
        return set()

    enabled_paths: set[str] = set()
    for entry in os.listdir(sites_enabled_dir):
        config_path = os.path.join(sites_enabled_dir, entry)
        if os.path.isfile(config_path) or os.path.islink(config_path):
            enabled_paths.add(os.path.realpath(config_path))
    return enabled_paths


def parse_nginx_dump(dump: str) -> list[VirtualHost]:
    # 1. Dosya marker'larına göre server bloklarını gez
    merged_by_config_path: dict[str, VirtualHost] = {}
    config_path = ""
    lines = dump.splitlines()
    index = 0

    while index < len(lines):
        marker = CONFIG_FILE_MARKER.match(lines[index].strip())
        if marker:
            config_path = marker.group("path").strip()
            index += 1
            continue

        if SERVER_BLOCK_START.match(lines[index]):
            block_lines, index = _read_server_block(lines, index)
            virtual_host = _virtual_host_from_block(config_path, block_lines)
            existing = merged_by_config_path.get(virtual_host.config_path)
            merged_by_config_path[virtual_host.config_path] = (
                _merge_virtual_hosts(existing, virtual_host)
                if existing
                else virtual_host
            )
            continue

        index += 1

    return list(merged_by_config_path.values())


def certificate_paths_from_dump(dump: str) -> list[str]:
    certificate_paths: list[str] = []

    for name, value in _directives_from_text(dump):
        if name != "ssl_certificate":
            continue
        path = value.strip('"')
        if path not in certificate_paths:
            certificate_paths.append(path)

    return certificate_paths


def _unparsed_virtual_host_from_command_failure(
    result: CommandResult,
    timeout: float,
) -> VirtualHost:
    if result.timed_out:
        parse_error = f"nginx -T timed out after {timeout:.1f}s"
    else:
        parse_error = (
            result.stderr.strip()[:MAX_PARSE_ERROR_LENGTH] or "nginx -T failed"
        )

    return VirtualHost(
        config_path="",
        parse_ok=False,
        parse_error=parse_error,
        raw_config=result.stdout[:MAX_RAW_CONFIG_LENGTH] or None,
    )


def _merge_virtual_hosts(first: VirtualHost, second: VirtualHost) -> VirtualHost:
    return VirtualHost(
        config_path=first.config_path,
        server_names=first.server_names + [
            name for name in second.server_names if name not in first.server_names
        ],
        listen_ports=sorted(set(first.listen_ports) | set(second.listen_ports)),
        upstream=first.upstream or second.upstream,
        ssl_enabled=first.ssl_enabled or second.ssl_enabled,
        cert_path=first.cert_path or second.cert_path,
        enabled=first.enabled and second.enabled,
        parse_ok=first.parse_ok and second.parse_ok,
        parse_error=first.parse_error or second.parse_error,
        raw_config=first.raw_config or second.raw_config,
    )


def _read_server_block(lines: list[str], start: int) -> tuple[list[str], int]:
    depth = 0
    block_lines: list[str] = []
    index = start

    while index < len(lines):
        line = lines[index]
        block_lines.append(line)
        depth += line.count("{") - line.count("}")
        index += 1
        if depth <= 0:
            break

    return block_lines, index


def _virtual_host_from_block(
    config_path: str,
    block_lines: list[str],
) -> VirtualHost:
    block_text = "\n".join(block_lines)

    if block_text.count("{") != block_text.count("}"):
        return VirtualHost(
            config_path=config_path,
            parse_ok=False,
            parse_error="unbalanced braces in server block",
            raw_config=block_text[:MAX_RAW_CONFIG_LENGTH],
        )

    server_names: list[str] = []
    listen_ports: list[int] = []
    upstream: str | None = None
    cert_path: str | None = None
    ssl_enabled = False

    for directive_name, directive_value in _directives_from_text(block_text):
        if directive_name == "server_name":
            server_names.extend(
                part for part in directive_value.split() if part != "_"
            )
        elif directive_name == "listen":
            port_number = _listen_port_number(directive_value)
            if port_number is not None and port_number not in listen_ports:
                listen_ports.append(port_number)
            if "ssl" in directive_value.split():
                ssl_enabled = True
        elif directive_name == "ssl_certificate":
            ssl_enabled = True
            if cert_path is None:
                cert_path = directive_value.strip('"')
        elif directive_name == "proxy_pass" and upstream is None:
            upstream = directive_value

    return VirtualHost(
        config_path=config_path,
        server_names=server_names,
        listen_ports=listen_ports,
        upstream=upstream,
        ssl_enabled=ssl_enabled,
        cert_path=cert_path,
        enabled=True,
        parse_ok=True,
    )


def _directives_from_text(text: str) -> list[tuple[str, str]]:
    uncommented = "\n".join(line.split("#", 1)[0] for line in text.splitlines())
    return [
        (match.group("name"), match.group("value").strip())
        for match in DIRECTIVE_PATTERN.finditer(uncommented)
    ]


def _listen_port_number(listen_value: str) -> int | None:
    first_token = listen_value.split()[0]

    if first_token.startswith("["):
        _, _, tail = first_token.rpartition("]:")
        candidate = tail
    elif ":" in first_token:
        candidate = first_token.rsplit(":", 1)[1]
    else:
        candidate = first_token

    try:
        return int(candidate)
    except ValueError:
        return None


EXPIRING_DAYS = 30
_REDIRECT_RETURN = re.compile(r"^\s*return\s+301\s+", re.MULTILINE)
_SERVER_NAME_LINE = re.compile(r"^\s*server_name\s+(?P<names>.+);")
_LISTEN_443 = re.compile(r"^\s*listen\s+.*443", re.MULTILINE)
_ADD_HEADER_LINE = re.compile(
    r'^\s*add_header\s+(?P<name>[^;\s]+)\s+"(?P<value>[^"]*)"(?:\s+always)?\s*;\s*$',
)
_LOCATION_ROOT_START = re.compile(r"^\s*location\s+/\s*\{")
_LOCATION_PREFIX_START = re.compile(r"^\s*location\s+(?P<path>/[^\s{~*]*)\s*\{")
_ALIAS_LINE = re.compile(r"^\s*alias\s+(?P<value>.+);\s*$")
_INDEX_LINE = re.compile(r"^\s*index\s+(?P<value>.+);\s*$")
_TRY_FILES_LINE = re.compile(r"^\s*try_files\s+(?P<value>.+);\s*$")
_ROOT_LINE = re.compile(r"^\s*root\s+(?P<value>.+);\s*$")
_LISTEN_LINE = re.compile(r"^\s*listen\s+(?P<value>.+);\s*$")


def parse_listen_directive(value: str) -> ListenEndpoint | None:
    cleaned = value.strip().strip(";")
    tokens = cleaned.split()
    if not tokens:
        return None

    ssl = "ssl" in tokens
    host_token = tokens[0]

    if host_token.startswith("["):
        _, _, port_str = host_token.partition("]:")
        if not port_str:
            return None
        try:
            port = int(port_str)
        except ValueError:
            return None
        inner = host_token[1 : host_token.index("]")]
        address = "::" if inner == "::" else inner
        return ListenEndpoint(port=port, ssl=ssl, address=address)

    if ":" in host_token:
        address, port_str = host_token.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            return None
        return ListenEndpoint(port=port, ssl=ssl, address=address or None)

    try:
        port = int(host_token)
    except ValueError:
        return None
    return ListenEndpoint(port=port, ssl=ssl, address=None)


def _listen_endpoints_from_block(block_lines: list[str]) -> list[ListenEndpoint]:
    endpoints: list[ListenEndpoint] = []
    for line in block_lines:
        if re.match(r"^\s*location\s+", line):
            break
        match = _LISTEN_LINE.match(line)
        if not match:
            continue
        endpoint = parse_listen_directive(match.group("value"))
        if endpoint is not None:
            endpoints.append(endpoint)
    return endpoints


def _extract_server_blocks(content: str) -> list[list[str]]:
    lines = content.splitlines()
    blocks: list[list[str]] = []
    index = 0
    while index < len(lines):
        if SERVER_BLOCK_START.match(lines[index]):
            start = index
            depth = 0
            while index < len(lines):
                depth += lines[index].count("{") - lines[index].count("}")
                index += 1
                if depth <= 0:
                    blocks.append(lines[start:index])
                    break
            continue
        index += 1
    return blocks


def _server_names_in_block(block_lines: list[str]) -> list[str]:
    names: list[str] = []
    for line in block_lines:
        match = _SERVER_NAME_LINE.match(line)
        if match:
            names.extend(part for part in match.group("names").split() if part != "_")
    return names


def _is_http_redirect_block(block_lines: list[str], domain: str) -> bool:
    names = _server_names_in_block(block_lines)
    if domain not in names:
        return False
    block_text = "\n".join(block_lines)
    if "www." in domain:
        return False
    if _LISTEN_443.search(block_text):
        return False
    if "proxy_pass" in block_text or re.search(r"^\s*root\s+", block_text, re.MULTILINE):
        return False
    return bool(_REDIRECT_RETURN.search(block_text))


def _is_www_redirect_block(block_lines: list[str], domain: str) -> bool:
    www_name = f"www.{domain}"
    names = _server_names_in_block(block_lines)
    if www_name not in names:
        return False
    block_text = "\n".join(block_lines)
    return bool(_REDIRECT_RETURN.search(block_text)) and domain in block_text


def _location_block_from_lines(path: str, block_lines: list[str]) -> LocationBlock:
    proxy_pass: str | None = None
    root: str | None = None
    alias: str | None = None
    try_files: str | None = None

    for line in block_lines:
        for directive_name, directive_value in _directives_from_text(line):
            if directive_name == "proxy_pass" and proxy_pass is None:
                proxy_pass = directive_value.strip().strip('"')
            elif directive_name == "root" and root is None:
                root = directive_value.strip().strip('"')
            elif directive_name == "try_files" and try_files is None:
                try_files = directive_value.strip().strip('"')
        alias_match = _ALIAS_LINE.match(line)
        if alias_match and alias is None:
            alias = alias_match.group("value").strip().strip('"')

    return LocationBlock(
        path=path,
        proxy_pass=proxy_pass,
        root=root,
        alias=alias,
        try_files=try_files,
    )


def _prefix_locations_from_block(block_lines: list[str]) -> list[LocationBlock]:
    locations: list[LocationBlock] = []
    index = 1
    while index < len(block_lines):
        match = _LOCATION_PREFIX_START.match(block_lines[index])
        if not match:
            index += 1
            continue

        path = match.group("path")
        depth = 0
        loc_lines: list[str] = []
        while index < len(block_lines):
            line = block_lines[index]
            loc_lines.append(line)
            depth += line.count("{") - line.count("}")
            index += 1
            if depth <= 0:
                break
        locations.append(_location_block_from_lines(path, loc_lines))
    return locations


async def precheck_certificate_domain(domain: str) -> tuple[list[str], list[str]]:
    import socket

    from iw_agent.modules.network.collector import collect_listening_ports

    errors: list[str] = []
    warnings: list[str] = []

    try:
        resolved = socket.gethostbyname(domain)
    except socket.OSError:
        errors.append(f"DNS: {domain} does not resolve")
        resolved = None

    if resolved is not None:
        local_addresses = _local_ip_addresses()
        if local_addresses and resolved not in local_addresses:
            warnings.append(
                f"DNS: {domain} points to {resolved}, not this host ({', '.join(sorted(local_addresses))})",
            )

    ports = await collect_listening_ports()
    if not any(port.port_number == 80 for port in ports):
        warnings.append("Port 80 is not listening — HTTP-01 challenge may fail")

    return errors, warnings


def _local_ip_addresses() -> set[str]:
    import socket

    addresses: set[str] = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addresses.add(info[4][0])
    except OSError:
        pass
    try:
        import psutil

        for addresses_list in psutil.net_if_addrs().values():
            for entry in addresses_list:
                if entry.family == socket.AF_INET and entry.address:
                    addresses.add(entry.address)
    except (ImportError, OSError):
        pass
    return addresses


async def collect_site_profiles(
    *,
    nginx_binary: str = DEFAULT_NGINX_BINARY,
    nginx_timeout: float = DEFAULT_NGINX_TIMEOUT_SECONDS,
    certbot_live_dir: str = DEFAULT_CERTBOT_LIVE_DIR,
) -> list[SiteProfile]:
    virtual_hosts = await collect_virtual_hosts(
        nginx_binary=nginx_binary,
        timeout=nginx_timeout,
    )
    dump_result = await fetch_nginx_dump(nginx_binary=nginx_binary, timeout=nginx_timeout)
    nginx_cert_paths = (
        certificate_paths_from_dump(dump_result.stdout)
        if dump_result is not None and dump_result.ok
        else []
    )
    certificates = await collect_certificates(
        certbot_live_dir=certbot_live_dir,
        nginx_cert_paths=nginx_cert_paths,
    )
    return [
        _build_site_profile(virtual_host, certificates)
        for virtual_host in virtual_hosts
        if virtual_host.parse_ok
    ]


def _build_site_profile(
    virtual_host: VirtualHost,
    certificates: list[Certificate],
) -> SiteProfile:
    certificate = _match_certificate(virtual_host, certificates)
    ssl_status = _resolve_ssl_status(virtual_host, certificate)
    return SiteProfile(
        virtual_host=virtual_host,
        certificate=certificate,
        ssl_status=ssl_status,
        recommendation=_recommendation_for(ssl_status),
    )


def _match_certificate(
    virtual_host: VirtualHost,
    certificates: list[Certificate],
) -> Certificate | None:
    if virtual_host.cert_path:
        cert_realpath = os.path.realpath(virtual_host.cert_path)
        for certificate in certificates:
            if os.path.realpath(certificate.cert_path) == cert_realpath:
                return certificate

    for name in virtual_host.server_names:
        for certificate in certificates:
            if certificate.domain == name:
                return certificate
            live_guess = f"/etc/letsencrypt/live/{name}/fullchain.pem"
            if os.path.realpath(certificate.cert_path) == os.path.realpath(live_guess):
                return certificate
    return None


def _resolve_ssl_status(
    virtual_host: VirtualHost,
    certificate: Certificate | None,
) -> SslStatus:
    if not virtual_host.ssl_enabled and certificate is None:
        return SslStatus.NO_SSL
    if virtual_host.ssl_enabled and certificate is None:
        return SslStatus.SSL_MISMATCH
    if certificate is None:
        return SslStatus.NO_SSL
    if virtual_host.server_names and certificate.domain not in virtual_host.server_names:
        return SslStatus.SSL_MISMATCH
    if certificate.not_after is None:
        return SslStatus.SSL_OK

    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    expiry = (
        certificate.not_after
        if certificate.not_after.tzinfo
        else certificate.not_after.replace(tzinfo=timezone.utc)
    )
    days = (expiry - now).days
    if days < 0:
        return SslStatus.SSL_EXPIRED
    if days <= EXPIRING_DAYS:
        return SslStatus.SSL_EXPIRING
    return SslStatus.SSL_OK


def _recommendation_for(status: SslStatus) -> str | None:
    if status == SslStatus.NO_SSL:
        return "Obtain HTTPS certificate"
    if status == SslStatus.SSL_EXPIRING:
        return "Renew certificate soon"
    if status == SslStatus.SSL_EXPIRED:
        return "Renew certificate immediately"
    if status == SslStatus.SSL_MISMATCH:
        return "Fix certificate mapping in nginx config"
    return None


if __name__ == "__main__":
    import asyncio
    import sys

    async def _main() -> None:
        nginx_binary = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NGINX_BINARY
        virtual_hosts = await collect_virtual_hosts(nginx_binary=nginx_binary)

        print(f"found {len(virtual_hosts)} virtual hosts\n")
        for virtual_host in virtual_hosts:
            if not virtual_host.parse_ok:
                print(
                    f"UNPARSED {virtual_host.config_path or '-'} "
                    f"error={virtual_host.parse_error}"
                )
                continue

            names = ",".join(virtual_host.server_names) or "-"
            ports = ",".join(str(port) for port in virtual_host.listen_ports) or "-"
            print(
                f"{virtual_host.config_path:<40} "
                f"names={names:<30} "
                f"ports={ports:<12} "
                f"ssl={virtual_host.ssl_enabled} "
                f"cert={virtual_host.cert_path or '-'} "
                f"upstream={virtual_host.upstream or '-'}"
            )

    asyncio.run(_main())
