from __future__ import annotations

import argparse
from datetime import datetime, timezone

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    print_column_guide,
    print_data_table,
    print_empty,
    print_insight,
    print_report,
    print_section,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.ssl.collector import DEFAULT_CERTBOT_LIVE_DIR, collect_certificates
from iw_agent.modules.ssl.schemas import Certificate

CERT_COLUMNS = [
    ("Website", "domain the certificate protects"),
    ("Issued by", "certificate authority"),
    ("Valid until", "expiry date — renew before this"),
    ("Source", "certbot or manual/nginx path"),
]


async def run_certs(args: argparse.Namespace) -> None:
    certificates = await collect_certificates(
        certbot_live_dir=args.certbot_live_dir,
        nginx_cert_paths=args.nginx_paths,
    )
    emit_models(certificates, json_output=args.json, plain=args.plain, render=_render_certs)


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

    print_insight(f"Found {len(certificates)} certificate(s) on this server.")

    print_section(1, "Certificate list", "Make sure expiry dates are in the future.")
    print_data_table(
        CERT_COLUMNS,
        [
            [
                certificate.domain,
                format_optional(certificate.issuer, fallback="unknown"),
                _expiry_label(certificate.not_after),
                certificate.source,
            ]
            for certificate in certificates
        ],
    )
    print_column_guide(CERT_COLUMNS)


def _expiry_label(not_after: datetime | None) -> str:
    if not_after is None:
        return "unknown"
    now = datetime.now(timezone.utc)
    expiry = not_after if not_after.tzinfo else not_after.replace(tzinfo=timezone.utc)
    days = (expiry - now).days
    text = expiry.strftime("%Y-%m-%d")
    if days < 0:
        return f"{text} (expired)"
    if days <= 14:
        return f"{text} (renew soon — {days} days left)"
    if days <= 30:
        return f"{text} ({days} days left)"
    return text


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
