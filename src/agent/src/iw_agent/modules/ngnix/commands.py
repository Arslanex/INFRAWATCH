from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_json,
    emit_models,
    format_optional,
    format_ssl_enabled,
    print_column_guide,
    print_data_table,
    print_empty,
    print_insight,
    print_labeled_rows,
    print_report,
    print_section,
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

NGINX_COLUMNS = [
    ("Website names", "domains served by this config"),
    ("Ports", "which ports accept web traffic"),
    ("Security", "whether HTTPS is configured"),
    ("Forwards to", "backend app address, if any"),
]


async def run_nginx(args: argparse.Namespace) -> None:
    virtual_hosts = await collect_virtual_hosts(
        nginx_binary=args.nginx_binary,
        timeout=args.timeout,
    )
    emit_models(virtual_hosts, json_output=args.json, plain=args.plain, render=_render_nginx)


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

    print_report(
        "Nginx configuration dump",
        "Raw config read from nginx for advanced inspection.",
    )

    if dump_result is None:
        print_empty(
            "nginx not available",
            "The nginx program is missing or could not be started.",
            "install nginx: sudo apt install nginx",
        )
        return

    print_labeled_rows(
        [
            ("Command result", "OK" if dump_result.ok else f"failed (exit {dump_result.exit_code})"),
            ("Timed out", "yes" if dump_result.timed_out else "no"),
        ]
    )

    cert_paths = certificate_paths_from_dump(dump_result.stdout)
    print_section(1, "Certificate files mentioned", "Paths nginx uses for HTTPS certificates.")
    if cert_paths:
        for cert_path in cert_paths:
            print(f"   • {cert_path}")
        print()
    else:
        print_empty("no certificate paths", "No ssl_certificate lines were found.", "check nginx config.")

    if args.show_stdout:
        print_section(2, "Raw nginx output", "Full text returned by nginx -T.")
        print(dump_result.stdout)


def _render_nginx(virtual_hosts: list[VirtualHost]) -> None:
    print_report(
        "Websites (nginx)",
        "Web addresses and ports configured on this server.",
    )

    parsed = [host for host in virtual_hosts if host.parse_ok]
    unparsed = [host for host in virtual_hosts if not host.parse_ok]

    if not parsed and not unparsed:
        print_empty(
            "no websites configured",
            "Nginx is not installed or has no server blocks.",
            "install nginx or check /etc/nginx",
        )
        return

    if parsed:
        print_insight(f"Found {len(parsed)} website configuration(s).")
        print_section(1, "Website list", "Each row is one site nginx can serve.")
        print_data_table(
            NGINX_COLUMNS,
            [
                [
                    ", ".join(virtual_host.server_names) or "(no name)",
                    ", ".join(str(port) for port in virtual_host.listen_ports) or "—",
                    format_ssl_enabled(virtual_host.ssl_enabled),
                    format_optional(virtual_host.upstream, fallback="—"),
                ]
                for virtual_host in parsed
            ],
        )
        print_column_guide(NGINX_COLUMNS)

    if unparsed:
        print_section(2, "Configuration problems", "These entries could not be read cleanly.")
        for virtual_host in unparsed:
            print(f"   • {format_optional(virtual_host.parse_error)}")
        print()


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
