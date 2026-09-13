from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    BOLD,
    DIM,
    GREEN,
    RED,
    YELLOW,
    _c,
    _reset,
    clear_screen,
    emit_json,
    emit_models,
    format_optional,
    format_strikethrough,
    print_empty,
    print_field_rows,
    print_insight,
    print_panel,
    print_report,
)
from iw_agent.cli.parser import add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.commands import CommandResult
from iw_agent.modules.ngnix.collector import (
    DEFAULT_NGINX_BINARY,
    DEFAULT_NGINX_TIMEOUT_SECONDS,
    certificate_paths_from_dump,
    collect_virtual_hosts,
    fetch_nginx_dump,
)
from iw_agent.modules.ngnix.schemas import VirtualHost

_FIELD_WIDTH = 11


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

    clear_screen()
    if dump_result is None:
        print_report(
            "Nginx raw config",
            "Advanced check — runs nginx -T on this server.",
        )
        print_empty(
            "nginx not available",
            "The nginx program is missing or could not be started.",
            "install nginx: sudo apt install nginx",
        )
        return

    _render_nginx_config(dump_result, show_stdout=args.show_stdout)


def _nginx_config_summary(dump_result: CommandResult, cert_paths: list[str]) -> str:
    if dump_result.timed_out:
        status = "timed out"
    elif dump_result.ok:
        status = "loaded OK"
    else:
        status = f"failed (exit {dump_result.exit_code})"
    return f"nginx -T {status} · {len(cert_paths)} certificate path(s) in config"


def _dump_status_fields(dump_result: CommandResult) -> list[tuple[str, str]]:
    if dump_result.timed_out:
        return [
            ("Status", f"{_c(RED)}TIMED OUT{_reset()}"),
            ("Why", "nginx -T did not finish before the timeout"),
        ]
    if dump_result.ok:
        return [
            ("Status", f"{_c(GREEN)}OK{_reset()}"),
            ("Why", "nginx merged all config files without errors"),
        ]
    return [
        ("Status", f"{_c(RED)}FAILED{_reset()}"),
        ("Why", "nginx reported a syntax or include error"),
    ]


def _render_cert_path(cert_path: str, index: int) -> None:
    label = cert_path.rsplit("/", 1)[-1] or cert_path
    print(f"   {_c(BOLD)}{index}. {label}{_reset()}")
    print(f"   {'-' * 48}")
    print_field_rows(
        [
            ("File", cert_path),
            ("Source", "ssl_certificate directive in nginx config"),
        ],
        label_width=_FIELD_WIDTH,
    )
    print()


def _render_nginx_config(dump_result: CommandResult, *, show_stdout: bool) -> None:
    cert_paths = certificate_paths_from_dump(dump_result.stdout)
    line_count = dump_result.stdout.count("\n") + (1 if dump_result.stdout else 0)

    print_report(
        "Nginx raw config",
        "Advanced check — not for everyday use. Try iw nginx for site overview.",
    )
    print_insight(_nginx_config_summary(dump_result, cert_paths))

    print_panel("How to read", hint="field guide")
    print_field_rows(
        [
            ("Purpose", "debug tool — dumps nginx's full merged config"),
            ("vs iw nginx", "iw nginx = readable sites  |  this = raw dump"),
            ("Status", "OK means nginx -T succeeded on this server"),
            ("Certs", "paths from ssl_certificate lines in that dump"),
            ("Raw text", "add --show-stdout to print the full nginx -T output"),
        ],
        label_width=_FIELD_WIDTH,
    )
    print()

    print_panel("Dump result", hint="nginx -T command")
    rows = [
        *_dump_status_fields(dump_result),
        ("Command", " ".join(dump_result.argv)),
        ("Exit code", str(dump_result.exit_code)),
        ("Output", f"{line_count} lines  {_c(DIM)}({len(dump_result.stdout)} chars){_reset()}"),
    ]
    if dump_result.stderr.strip():
        stderr_preview = dump_result.stderr.strip().replace("\n", " · ")
        if len(stderr_preview) > 120:
            stderr_preview = f"{stderr_preview[:117]}..."
        rows.append(("Errors", stderr_preview))
    print_field_rows(rows, label_width=_FIELD_WIDTH)
    print()

    print_panel("Certificate paths", hint="files nginx references for HTTPS")
    if cert_paths:
        for index, cert_path in enumerate(cert_paths, start=1):
            _render_cert_path(cert_path, index)
    else:
        print_empty(
            "no certificate paths",
            "No ssl_certificate lines were found in the dump.",
            "sites may be HTTP only, or config failed to load.",
        )

    if show_stdout:
        print_panel("Raw output", hint="full nginx -T text")
        print_field_rows(
            [
                ("Status", "printed below"),
                ("Why", "for advanced debugging only — can be very long"),
            ],
            label_width=_FIELD_WIDTH,
        )
        print()
        print(dump_result.stdout)


def _nginx_summary(virtual_hosts: list[VirtualHost]) -> str:
    parsed = [host for host in virtual_hosts if host.parse_ok]
    active = sum(1 for host in parsed if host.enabled)
    disabled = sum(1 for host in parsed if not host.enabled)
    secured = sum(1 for host in parsed if host.enabled and host.ssl_enabled)
    return (
        f"{len(parsed)} site(s): {active} live, {disabled} off, {secured} with HTTPS."
    )


def _site_title(virtual_host: VirtualHost) -> str:
    names = ", ".join(virtual_host.server_names)
    if names:
        return names
    return virtual_host.config_path.rsplit("/", 1)[-1] or "(unnamed site)"


def _status_fields(virtual_host: VirtualHost) -> list[tuple[str, str]]:
    if virtual_host.enabled:
        return [
            ("Status", f"{_c(GREEN)}LIVE{_reset()}"),
            ("Why", "nginx loaded and serves this config"),
        ]
    return [
        ("Status", f"{_c(DIM)}OFF{_reset()}"),
        ("Why", "in sites-available but not linked in sites-enabled"),
    ]


def _security_field(virtual_host: VirtualHost) -> tuple[str, str]:
    if not virtual_host.enabled:
        return ("Security", f"{_c(DIM)}n/a (site is off){_reset()}")
    if virtual_host.ssl_enabled:
        return ("Security", f"{_c(GREEN)}HTTPS{_reset()}  encrypted web traffic")
    return ("Security", f"{_c(YELLOW)}HTTP only{_reset()}  no TLS certificate here")


def _ports_field(virtual_host: VirtualHost) -> tuple[str, str]:
    if not virtual_host.listen_ports:
        return ("Ports", f"{_c(DIM)}none found{_reset()}")
    port_text = ", ".join(str(port) for port in sorted(virtual_host.listen_ports))
    note = "public web ports" if any(
        port in {80, 443, 8080, 8443} for port in virtual_host.listen_ports
    ) else "listening ports"
    return ("Ports", f"{port_text}  {_c(DIM)}({note}){_reset()}")


def _render_site(virtual_host: VirtualHost) -> None:
    title = _site_title(virtual_host)
    if not virtual_host.enabled:
        title = format_strikethrough(title)

    print(f"   {_c(BOLD)}{title}{_reset()}")
    print(f"   {'-' * 48}")

    rows = [
        *_status_fields(virtual_host),
        _security_field(virtual_host),
        _ports_field(virtual_host),
    ]

    if virtual_host.upstream:
        rows.append(
            (
                "Forwards",
                f"{virtual_host.upstream}  {_c(DIM)}(backend target){_reset()}",
            )
        )

    if virtual_host.cert_path:
        rows.append(("Cert file", virtual_host.cert_path))

    rows.append(("Config", virtual_host.config_path))

    print_field_rows(rows, label_width=_FIELD_WIDTH)
    print()


def _render_nginx(virtual_hosts: list[VirtualHost]) -> None:
    print_report(
        "Websites (nginx)",
        "Which sites nginx serves, on which ports, with what security.",
    )

    parsed = [host for host in virtual_hosts if host.parse_ok]
    unparsed = [host for host in virtual_hosts if not host.parse_ok]
    active_hosts = [host for host in parsed if host.enabled]
    disabled_hosts = [host for host in parsed if not host.enabled]

    if not parsed and not unparsed:
        print_empty(
            "no websites configured",
            "Nginx is not installed or has no server blocks.",
            "install nginx or check /etc/nginx",
        )
        return

    if parsed:
        print_insight(_nginx_summary(parsed))

        print_panel("How to read", hint="field guide")
        print_field_rows(
            [
                ("Status", "LIVE = nginx serves it now  |  OFF = disabled config file"),
                ("Security", "HTTPS = encrypted  |  HTTP only = no TLS"),
                ("Forwards", "where nginx sends requests inside the server"),
                ("Config", "file path on this machine"),
            ],
            label_width=_FIELD_WIDTH,
        )
        print()

        if active_hosts:
            print_panel("Live sites", hint="currently served by nginx")
            for virtual_host in active_hosts:
                _render_site(virtual_host)

        if disabled_hosts:
            print_panel("Disabled sites", hint="not loaded — safe to ignore unless enabling")
            for virtual_host in disabled_hosts:
                _render_site(virtual_host)

    if unparsed:
        print_panel("Problems", hint="configs that could not be parsed")
        for virtual_host in unparsed:
            print(f"   {_c(RED)}!{_reset()} {format_optional(virtual_host.parse_error)}")
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
        "advanced nginx -T dump and cert paths",
        run_nginx_config,
        _configure_nginx_config,
    ),
]
