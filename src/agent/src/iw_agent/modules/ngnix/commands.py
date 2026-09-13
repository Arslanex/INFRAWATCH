from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    DIM,
    _c,
    _reset,
    clear_screen,
    emit_json,
    emit_models,
    format_field,
    format_fields,
    format_nginx_exposure,
    format_nginx_security,
    format_nginx_status_badge,
    format_optional,
    print_empty,
    print_group_heading,
    print_info_box,
    print_insight,
    print_report,
    print_status_box,
    status_badge,
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


def _dump_badge(dump_result: CommandResult) -> tuple[str, str]:
    if dump_result.timed_out:
        return status_badge("TIMED OUT", "bad"), "bad"
    if dump_result.ok:
        return status_badge("OK", "ok"), "ok"
    return status_badge("FAILED", "bad"), "bad"


def _render_cert_path(cert_path: str, index: int) -> None:
    label = cert_path.rsplit("/", 1)[-1] or cert_path
    print_info_box(
        title=f"{index}. {label}",
        hint="ssl_certificate path",
        lines=format_fields(
            [
                ("File", cert_path),
                ("Source", "ssl_certificate directive in nginx config"),
            ]
        ),
    )


def _render_nginx_config(dump_result: CommandResult, *, show_stdout: bool) -> None:
    cert_paths = certificate_paths_from_dump(dump_result.stdout)
    line_count = dump_result.stdout.count("\n") + (1 if dump_result.stdout else 0)
    badge, tone = _dump_badge(dump_result)

    print_report(
        "Nginx raw config",
        "Advanced check — not for everyday use. Try iw nginx for site overview.",
    )
    print_insight(_nginx_config_summary(dump_result, cert_paths))

    print_info_box(
        title="How to read",
        hint="field guide",
        lines=format_fields(
            [
                ("Purpose", "debug tool — dumps nginx's full merged config"),
                ("vs iw nginx", "iw nginx = readable sites  |  this = raw dump"),
                ("Status", "OK means nginx -T succeeded on this server"),
                ("Certs", "paths from ssl_certificate lines in that dump"),
                ("Raw text", "add --show-stdout to print the full nginx -T output"),
            ]
        ),
    )

    dump_lines = [
        format_field(
            "Why",
            "nginx merged all config files without errors"
            if dump_result.ok
            else "nginx reported a syntax or include error",
        ),
        format_field("Command", " ".join(dump_result.argv)),
        format_field("Exit code", str(dump_result.exit_code)),
        format_field(
            "Output",
            f"{line_count} lines  {_c(DIM)}({len(dump_result.stdout)} chars){_reset()}",
        ),
    ]
    if dump_result.stderr.strip():
        stderr_preview = dump_result.stderr.strip().replace("\n", " · ")
        if len(stderr_preview) > 120:
            stderr_preview = f"{stderr_preview[:117]}..."
        dump_lines.append(format_field("Errors", stderr_preview))

    print_status_box(
        badge=badge,
        title="nginx -T dump",
        lines=dump_lines,
        tone=tone,
    )

    print_group_heading("Certificate paths", "files nginx references for HTTPS")
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
        print_info_box(
            title="Raw output",
            hint="full nginx -T text — printed below",
            lines=format_fields(
                [
                    ("Why", "for advanced debugging only — can be very long"),
                ]
            ),
        )
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


def _site_lines(virtual_host: VirtualHost) -> list[str]:
    why = (
        "nginx loaded and serves this config"
        if virtual_host.enabled
        else "in sites-available but not linked in sites-enabled"
    )
    lines = [
        format_field("Why", why),
        format_field(
            "Security",
            format_nginx_security(
                site_enabled=virtual_host.enabled,
                ssl_enabled=virtual_host.ssl_enabled,
            ),
        ),
        format_field(
            "Ports",
            format_nginx_exposure(virtual_host.listen_ports),
        ),
    ]

    if virtual_host.upstream:
        lines.append(
            format_field(
                "Forwards",
                f"{virtual_host.upstream}  {_c(DIM)}(backend target){_reset()}",
            )
        )

    if virtual_host.cert_path:
        lines.append(format_field("Cert file", virtual_host.cert_path))

    lines.append(format_field("Config", virtual_host.config_path))
    return lines


def _render_site(virtual_host: VirtualHost) -> None:
    tone = "ok" if virtual_host.enabled else "off"
    print_status_box(
        badge=format_nginx_status_badge(site_enabled=virtual_host.enabled),
        title=_site_title(virtual_host),
        lines=_site_lines(virtual_host),
        tone=tone,
        strike_title=not virtual_host.enabled,
    )


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

        print_info_box(
            title="How to read",
            hint="field guide",
            lines=format_fields(
                [
                    ("Status", "LIVE = nginx serves it now  |  OFF = disabled config file"),
                    ("Security", "HTTPS = encrypted  |  HTTP only = no TLS"),
                    ("Forwards", "where nginx sends requests inside the server"),
                    ("Config", "file path on this machine"),
                ]
            ),
        )

        if active_hosts:
            print_group_heading("Live sites", "currently served by nginx")
            for virtual_host in active_hosts:
                _render_site(virtual_host)

        if disabled_hosts:
            print_group_heading("Disabled sites", "not loaded — safe to ignore unless enabling")
            for virtual_host in disabled_hosts:
                _render_site(virtual_host)

    if unparsed:
        print_group_heading("Problems", "configs that could not be parsed")
        for virtual_host in unparsed:
            print_info_box(
                title="Parse error",
                lines=[format_field("Detail", format_optional(virtual_host.parse_error))],
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
        "advanced nginx -T dump and cert paths",
        run_nginx_config,
        _configure_nginx_config,
    ),
]
