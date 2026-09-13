from __future__ import annotations

import argparse
from datetime import datetime, timezone

from iw_agent.cli.output import (
    BOLD,
    DIM,
    _c,
    _reset,
    cert_expiry_details,
    emit_models,
    format_horizontal_bar,
    format_optional,
    format_strikethrough,
    print_empty,
    print_field_rows,
    print_insight,
    print_panel,
    print_report,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.ssl.collector import DEFAULT_CERTBOT_LIVE_DIR, collect_certificates
from iw_agent.modules.ssl.schemas import Certificate

_FIELD_WIDTH = 11


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


def _why_field(tone: str) -> tuple[str, str]:
    if tone == "bad":
        return ("Why", "HTTPS visitors will see security warnings")
    if tone == "warn":
        return ("Why", "renew before expiry to avoid downtime")
    if tone == "ok":
        return ("Why", "protects HTTPS traffic for this domain")
    return ("Why", "expiry date could not be read from file")


def _render_certificate(certificate: Certificate) -> None:
    status_label, expiry_text, bar_percent, tone = cert_expiry_details(certificate.not_after)
    bar = format_horizontal_bar(bar_percent, width=28)

    title = certificate.domain
    if tone == "bad":
        title = format_strikethrough(title)

    print(f"   {_c(BOLD)}{title}{_reset()}")
    print(f"   {'-' * 48}")

    rows = [
        ("Status", status_label),
        _why_field(tone),
        ("Expires", expiry_text),
        ("Time left", f"[{bar}]  {_c(DIM)}({bar_percent:.0f}% of 90-day window){_reset()}"),
        ("Issuer", format_optional(certificate.issuer, fallback="unknown")),
        ("Source", certificate.source),
        ("File", certificate.cert_path),
    ]
    print_field_rows(rows, label_width=_FIELD_WIDTH)
    print()


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

    print_panel("How to read", hint="field guide")
    print_field_rows(
        [
            ("Status", "VALID / EXPIRING / RENEW SOON / EXPIRED"),
            ("Expires", "last day the certificate works"),
            ("Time left", "bar shows remaining time (90-day scale)"),
            ("Source", "certbot, nginx path, or other"),
            ("File", "certificate path on this server"),
        ],
        label_width=_FIELD_WIDTH,
    )
    print()

    for panel_title, panel_hint, group in _group_certificates(certificates):
        if not group:
            continue
        print_panel(panel_title, hint=panel_hint)
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
