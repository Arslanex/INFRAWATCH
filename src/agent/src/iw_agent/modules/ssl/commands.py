from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    print_result_count,
    print_table,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.ssl.collector import DEFAULT_CERTBOT_LIVE_DIR, collect_certificates
from iw_agent.modules.ssl.schemas import Certificate


async def run_certs(args: argparse.Namespace) -> None:
    certificates = await collect_certificates(
        certbot_live_dir=args.certbot_live_dir,
        nginx_cert_paths=args.nginx_paths,
    )
    emit_models(certificates, json_output=args.json, render=_render_certs)


def _render_certs(certificates: list[Certificate]) -> None:
    print_result_count("certificate", len(certificates))
    print_table(
        ["DOMAIN", "ISSUER", "EXPIRES", "SOURCE", "PATH"],
        [
            [
                certificate.domain,
                format_optional(certificate.issuer),
                format_optional(certificate.not_after),
                certificate.source,
                certificate.cert_path,
            ]
            for certificate in certificates
        ],
        widths=[24, 16, 22, 10, 36],
    )


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
