"""Full-screen certificate picker for ``iw certs -i``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from iw_agent.cli.output import (
    cert_expiry_details,
    format_field,
    format_meter,
    format_optional,
)
from iw_agent.cli.tui.card_picker import CardItem, PickResult, pick_card
from iw_agent.cli.tui.cards import card_lines
from iw_agent.modules.ssl.schemas import Certificate

FOOTER = "↑↓ select  enter open  q quit"

_WHY_TEXT = {
    "bad": "HTTPS visitors will see security warnings",
    "warn": "renew before expiry to avoid downtime",
    "ok": "protects HTTPS traffic for this domain",
}


@dataclass(frozen=True)
class CertListChoice:
    kind: Literal["cert", "obtain"]
    certificate: Certificate | None = None


def _cert_card(certificate: Certificate) -> CardItem[CertListChoice]:
    _badge, _status, expiry_text, bar_percent, tone = cert_expiry_details(
        certificate.not_after,
    )
    body = [
        format_field(
            "Why",
            _WHY_TEXT.get(tone, "expiry date could not be read from file"),
        ),
        format_field("Expires", expiry_text),
        format_field("Left", format_meter("Left", bar_percent).strip()),
        format_field("Issuer", format_optional(certificate.issuer, fallback="unknown")),
        format_field("Source", certificate.source),
    ]
    return CardItem(
        lines=card_lines(certificate.domain, body, strike_title=tone == "bad"),
        value=CertListChoice(kind="cert", certificate=certificate),
    )


def _obtain_card() -> CardItem[CertListChoice]:
    body = [
        format_field("Why", "get a new Let's Encrypt cert via certbot"),
        format_field("Hint", "domain → email → nginx or webroot"),
    ]
    return CardItem(
        lines=card_lines("Obtain new certificate", body),
        value=CertListChoice(kind="obtain"),
    )


def cert_list_cards(certificates: list[Certificate]) -> list[CardItem[CertListChoice]]:
    return [_cert_card(certificate) for certificate in certificates] + [_obtain_card()]


async def pick_certificate(
    certificates: list[Certificate],
    *,
    summary: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[CertListChoice]:
    return await pick_card(
        cert_list_cards(certificates),
        title="Certificates",
        subtitle="ssl",
        summary=summary,
        footer=FOOTER,
        dry_run=dry_run,
        terminal=terminal,
    )
