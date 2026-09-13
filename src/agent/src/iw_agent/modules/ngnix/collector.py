from __future__ import annotations

import re

from iw_agent.core.commands import CommandResult, is_command_available, run_command
from iw_agent.core.exceptions import (
    NginxCommandFailedError,
    NginxCommandStartError,
    NginxNotInstalledError,
    NginxTimeoutError,
)
from iw_agent.core.logger import logger
from iw_agent.modules.ngnix.schemas import VirtualHost

CONFIG_FILE_MARKER = re.compile(r"^#\s*configuration file (?P<path>.+):$")
SERVER_BLOCK_START = re.compile(r"^\s*server\s*\{")
DIRECTIVE_PATTERN = re.compile(r"(?P<name>[a-z_]+)\s+(?P<value>[^;{}]+);")

DEFAULT_NGINX_BINARY = "nginx"
DEFAULT_NGINX_TIMEOUT_SECONDS = 30.0
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

    # 4. Dump'ı parse et
    virtual_hosts = parse_nginx_dump(dump_result.stdout)
    logger.debug("collected %d nginx virtual hosts", len(virtual_hosts))
    return virtual_hosts


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
