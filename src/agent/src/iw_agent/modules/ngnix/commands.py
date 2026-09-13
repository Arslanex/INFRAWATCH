from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_json,
    emit_models,
    format_optional,
    print_result_count,
    print_table,
)
from iw_agent.cli.parser import add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.ngnix.collector import (
    DEFAULT_NGINX_BINARY,
    DEFAULT_NGINX_TIMEOUT_SECONDS,
    certificate_paths_from_dump,
    collect_virtual_hosts,
    fetch_nginx_dump,
)
from iw_agent.modules.ngnix.schemas import VirtualHost


async def run_nginx(args: argparse.Namespace) -> None:
    virtual_hosts = await collect_virtual_hosts(
        nginx_binary=args.nginx_binary,
        timeout=args.timeout,
    )
    emit_models(virtual_hosts, json_output=args.json, render=_render_nginx)


async def run_nginx_config(args: argparse.Namespace) -> None:
    dump_result = await fetch_nginx_dump(
        nginx_binary=args.nginx_binary,
        timeout=args.timeout,
    )

    if args.json:
        if dump_result is None:
            emit_json({"ok": False, "stdout": "", "cert_paths": []})
            return
        emit_json(
            {
                "ok": dump_result.ok,
                "timed_out": dump_result.timed_out,
                "exit_code": dump_result.exit_code,
                "cert_paths": certificate_paths_from_dump(dump_result.stdout),
                "stdout": dump_result.stdout,
            }
        )
        return

    if dump_result is None:
        print("Could not run nginx -T (binary missing or failed to start).")
        return

    print(f"exit code: {dump_result.exit_code}  timed out: {dump_result.timed_out}")
    cert_paths = certificate_paths_from_dump(dump_result.stdout)
    print_result_count("certificate path", len(cert_paths))
    for cert_path in cert_paths:
        print(f"  {cert_path}")

    if args.show_stdout:
        print("\n--- nginx -T stdout ---\n")
        print(dump_result.stdout)


def _render_nginx(virtual_hosts: list[VirtualHost]) -> None:
    print_result_count("virtual host", len(virtual_hosts))
    print_table(
        ["CONFIG", "NAMES", "PORTS", "SSL", "CERT", "UPSTREAM"],
        [
            [
                virtual_host.config_path or "-",
                ",".join(virtual_host.server_names) or "-",
                ",".join(str(port) for port in virtual_host.listen_ports) or "-",
                "yes" if virtual_host.ssl_enabled else "no",
                format_optional(virtual_host.cert_path),
                format_optional(virtual_host.upstream),
            ]
            for virtual_host in virtual_hosts
            if virtual_host.parse_ok
        ],
        widths=[28, 20, 12, 5, 28, 16],
    )

    unparsed = [host for host in virtual_hosts if not host.parse_ok]
    for virtual_host in unparsed:
        print(
            f"\n  parse error: {format_optional(virtual_host.parse_error)}"
        )


def _configure_nginx(parser: argparse.ArgumentParser) -> None:
    add_timeout_flag(parser, default=DEFAULT_NGINX_TIMEOUT_SECONDS)
    parser.add_argument(
        "--binary",
        dest="nginx_binary",
        default=DEFAULT_NGINX_BINARY,
        help=f"nginx binary (default: {DEFAULT_NGINX_BINARY})",
    )


def _configure_nginx_config(parser: argparse.ArgumentParser) -> None:
    _configure_nginx(parser)
    parser.add_argument(
        "--show-stdout",
        action="store_true",
        help="print raw nginx -T output",
    )


COMMAND_SPECS = [
    CliCommandSpec("nginx", "nginx virtual hosts", run_nginx, _configure_nginx),
    CliCommandSpec(
        "nginx-config",
        "nginx -T dump and certificate paths",
        run_nginx_config,
        _configure_nginx_config,
    ),
]
