"""Action picker for a selected SSL certificate."""
from __future__ import annotations

from iw_agent.cli.output import cert_expiry_details
from iw_agent.cli.tui.card_picker import PickResult
from iw_agent.cli.interactive.hub import HubAction, pick_hub_action
from iw_agent.modules.ssl.schemas import Certificate


def hub_actions(certificate: Certificate) -> list[HubAction]:
    actions: list[HubAction] = []

    if certificate.source == "certbot":
        _badge, status, _text, _bar, tone = cert_expiry_details(certificate.not_after)
        renew_hint = "certbot renew --cert-name"
        if tone in {"bad", "warn"}:
            renew_hint = f"{status.lower()} — renew with certbot"
        actions.append(HubAction("Renew certificate", renew_hint, "renew_certificate"))

    actions.append(
        HubAction("View details", "domain, issuer, expiry, path", "view_certificate"),
    )
    return actions


async def pick_cert_action(
    certificate: Certificate,
    *,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[HubAction]:
    return await pick_hub_action(
        hub_actions(certificate),
        title=certificate.domain,
        subtitle="ssl · actions",
        dry_run=dry_run,
        terminal=terminal,
    )
