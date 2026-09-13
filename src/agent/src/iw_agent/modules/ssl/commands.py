from __future__ import annotations

import argparse
from datetime import datetime, timezone

from iw_agent.cli.output import (
    DIM,
    _c,
    _reset,
    cert_expiry_details,
    emit_models,
    format_horizontal_bar,
    format_optional,
    print_empty,
    print_info_card,
    print_insight,
    print_report,
    print_section,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.ssl.collector import DEFAULT_CERTBOT_LIVE_DIR, collect_certificates
from iw_agent.modules.ssl.schemas import Certificate


async def run_certs(args: argparse.Namespace) -> None:
    certificates = await collect_certificates(
        certbot_live_dir=args.certbot_live_dir,
        nginx_cert_paths=args.nginx_paths,
    )
    emit_models(certificates, json_output=args.json, plain=args.plain, render=_render_certs)


def _certs_summary(certificates: list[Certificate]) -> str:
    now = datetime.now(timezone.utc)
    valid = 0
    expiring = 0
    expired = 0

    for certificate in certificates:
        if certificate.not_after is None:
            continue
        expiry = (
            certificate.not_after
            if certificate.not_after.tzinfo
            else certificate.not_after.replace(tzinfo=timezone.utc)
        )
        days = (expiry - now).days
        if days < 0:
            expired += 1
        elif days <= 30:
            expiring += 1
        else:
            valid += 1

    return (
        f"Found {len(certificates)} certificate(s): "
        f"{valid} valid, {expiring} expiring soon, {expired} expired."
    )


def _render_cert_card(certificate: Certificate) -> None:
    badge, status_line, bar_percent, tone = cert_expiry_details(certificate.not_after)
    bar = format_horizontal_bar(bar_percent, width=24)

    lines = [
        status_line,
        f"[{bar}]",
        f"{_c(DIM)}issuer:{_reset()} {format_optional(certificate.issuer, fallback='unknown')}",
        f"{_c(DIM)}source:{_reset()} {certificate.source}",
        f"{_c(DIM)}file:{_reset()} {certificate.cert_path}",
    ]

    print_info_card(
        badge=badge,
        title=certificate.domain,
        lines=lines,
        tone=tone,
        strike_title=tone == "bad",
    )


def _render_certs(certificates: list[Certificate]) -> None:
    print_report(
        "SSL certificates",
        "Security certificates used for HTTPS on websites.",
    )
    if not certificates:
        print_empty(
            "no certificates found",
            "No readable certificate files were discovered.",
            "check /etc/letsencrypt or nginx ssl_certificate paths.",
        )
        return

    print_insight(_certs_summary(certificates))

    expired = []
    expiring = []
    valid = []
    unknown = []

    for certificate in certificates:
        if certificate.not_after is None:
            unknown.append(certificate)
            continue
        expiry = (
            certificate.not_after
            if certificate.not_after.tzinfo
            else certificate.not_after.replace(tzinfo=timezone.utc)
        )
        days = (expiry - datetime.now(timezone.utc)).days
        if days < 0:
            expired.append(certificate)
        elif days <= 30:
            expiring.append(certificate)
        else:
            valid.append(certificate)

    step = 1
    groups = [
        (expired, "Expired certificates", "These no longer protect HTTPS traffic."),
        (expiring, "Expiring soon", "Renew these before the expiry date."),
        (valid, "Valid certificates", "These certificates are still good."),
        (unknown, "Unknown expiry", "Could not read the expiry date."),
    ]

    for group, title, description in groups:
        if not group:
            continue
        print_section(step, title, description)
        step += 1
        for certificate in group:
            _render_cert_card(certificate)


def _configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--certbot-dir",
        dest="certbot_live_dir",
        default=DEFAULT_CERTBOT_LIVE_DIR,
        help=f"certbot live directory (default: {DEFAULT_CERTBOT_LIVE_DIR})",
    )
    parser.add_argument(
        "nginx_paths",
        nargs="*",
        default=[],
        help="extra certificate file paths",
    )


COMMAND_SPECS = [
    CliCommandSpec("certs", "ssl certificates on disk", run_certs, _configure),
]
