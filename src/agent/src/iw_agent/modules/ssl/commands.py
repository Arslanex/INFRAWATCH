from __future__ import annotations

import argparse
from datetime import datetime, timezone

from iw_agent.cli.output import (
    DIM,
    _c,
    _reset,
    cert_expiry_details,
    emit_models,
    format_field,
    format_fields,
    format_meter,
    format_optional,
    format_strikethrough,
    print_empty,
    print_group_heading,
    print_info_box,
    print_insight,
    print_report,
    print_status_box,
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

    return f"{len(certificates)} cert(s): {valid} valid, {expiring} expiring, {expired} expired."


def _why_text(tone: str) -> str:
    if tone == "bad":
        return "HTTPS visitors will see security warnings"
    if tone == "warn":
        return "renew before expiry to avoid downtime"
    if tone == "ok":
        return "protects HTTPS traffic for this domain"
    return "expiry date could not be read from file"


def _render_certificate(certificate: Certificate) -> None:
    badge, _status, expiry_text, bar_percent, tone = cert_expiry_details(certificate.not_after)
    title = certificate.domain
    if tone == "bad":
        title = format_strikethrough(title)

    lines = [
        format_field("Why", _why_text(tone)),
        format_field("Expires", expiry_text),
        format_meter("Left", bar_percent)
        + f"  {_c(DIM)}({bar_percent:.0f}% of 90-day window){_reset()}",
        format_field("Issuer", format_optional(certificate.issuer, fallback="unknown")),
        format_field("Source", certificate.source),
        format_field("File", certificate.cert_path),
    ]

    print_status_box(
        badge=badge,
        title=title,
        lines=lines,
        tone=tone,
        strike_title=tone == "bad",
    )


def _group_certificates(
    certificates: list[Certificate],
) -> list[tuple[str, str, list[Certificate]]]:
    now = datetime.now(timezone.utc)
    expired: list[Certificate] = []
    expiring: list[Certificate] = []
    valid: list[Certificate] = []
    unknown: list[Certificate] = []

    for certificate in certificates:
        if certificate.not_after is None:
            unknown.append(certificate)
            continue
        expiry = (
            certificate.not_after
            if certificate.not_after.tzinfo
            else certificate.not_after.replace(tzinfo=timezone.utc)
        )
        days = (expiry - now).days
        if days < 0:
            expired.append(certificate)
        elif days <= 30:
            expiring.append(certificate)
        else:
            valid.append(certificate)

    return [
        ("Expired", "no longer valid — renew immediately", expired),
        ("Expiring soon", "renew within the next 30 days", expiring),
        ("Valid", "still protecting HTTPS", valid),
        ("Unknown", "expiry date missing", unknown),
    ]


def _render_certs(certificates: list[Certificate]) -> None:
    print_report(
        "SSL certificates",
        "Which HTTPS certificates exist, when they expire, and where they live.",
    )
    if not certificates:
        print_empty(
            "no certificates found",
            "No readable certificate files were discovered.",
            "check /etc/letsencrypt or nginx ssl_certificate paths.",
        )
        return

    print_insight(_certs_summary(certificates))

    print_info_box(
        title="How to read",
        hint="field guide",
        lines=format_fields(
            [
                ("Status", "VALID / EXPIRING / RENEW SOON / EXPIRED"),
                ("Expires", "last day the certificate works"),
                ("Left", "bar shows remaining time on a 90-day scale"),
                ("Source", "certbot, nginx path, or other"),
                ("File", "certificate path on this server"),
            ]
        ),
    )

    for panel_title, panel_hint, group in _group_certificates(certificates):
        if not group:
            continue
        print_group_heading(panel_title, panel_hint)
        for certificate in group:
            _render_certificate(certificate)


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
