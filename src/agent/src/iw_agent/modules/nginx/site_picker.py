"""Full-screen site picker for ``iw nginx -i``.

Compact cards (domain, why, security, certificate) over the shared card picker.
**New site** is always first; ``o`` toggles a site, ``enter`` opens the editor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from iw_agent.cli.output import format_field, format_nginx_security
from iw_agent.cli.tui.card_picker import CardItem, CardPickerUnavailable, pick_card
from iw_agent.cli.tui.cards import card_lines
from iw_agent.modules.nginx.schemas import SiteProfile, VirtualHost

FOOTER = "↑↓ select  enter open  q quit"
FOOTER_SITE = "↑↓ select  o enable/disable  enter edit  q quit"
KEY_HINTS = {"o": "! Select a site first"}

SitePickerUnavailable = CardPickerUnavailable

_SSL_LABELS = {
    "no_ssl": "no SSL",
    "ssl_ok": "HTTPS ok",
    "ssl_expiring": "expiring",
    "ssl_expired": "expired",
    "ssl_mismatch": "mismatch",
    "ssl_orphan": "orphan",
}


@dataclass(frozen=True)
class SitePickOutcome:
    kind: Literal["quit", "new", "open", "toggle"]
    host: VirtualHost | None = None


@dataclass(frozen=True)
class _SiteChoice:
    kind: Literal["new", "site"]
    host: VirtualHost | None = None


def _new_site_card() -> CardItem[_SiteChoice]:
    return CardItem(
        lines=card_lines(
            "Create a new site",
            [format_field("Next", "minimal skeleton → structural editor")],
        ),
        value=_SiteChoice(kind="new"),
        footer=FOOTER,
    )


def _site_card(profile: SiteProfile) -> CardItem[_SiteChoice]:
    host = profile.virtual_host
    why = (
        "nginx loaded and serves this config"
        if host.enabled
        else "in sites-available but not linked in sites-enabled"
    )
    if host.enabled:
        action = "o disable site · enter edit config"
    else:
        action = "o enable site (symlink + reload) · enter edit"
    body = [
        format_field("Why", why),
        format_field(
            "Security",
            format_nginx_security(site_enabled=host.enabled, ssl_enabled=host.ssl_enabled),
        ),
        format_field("Certificate", _SSL_LABELS.get(profile.ssl_status.value, profile.ssl_status.value)),
        format_field("Action", action),
    ]
    title = ", ".join(host.server_names) or host.config_path.rsplit("/", 1)[-1] or "(unnamed site)"
    return CardItem(
        lines=card_lines(title, body, strike_title=not host.enabled),
        value=_SiteChoice(kind="site", host=host),
        footer=FOOTER_SITE,
        keys={"o": "toggle"},
    )


def site_cards(profiles: list[SiteProfile]) -> list[CardItem[_SiteChoice]]:
    return [_new_site_card()] + [_site_card(profile) for profile in profiles]


async def pick_site(
    profiles: list[SiteProfile],
    *,
    summary: str,
    dry_run: bool = False,
    status: str = "",
    terminal=None,
) -> SitePickOutcome:
    picked = await pick_card(
        site_cards(profiles),
        title="Websites (nginx)",
        subtitle="pick a site to edit",
        summary=summary,
        footer=FOOTER,
        dry_run=dry_run,
        status=status,
        key_hints=KEY_HINTS,
        terminal=terminal,
    )
    choice = picked.value
    if choice is None:
        return SitePickOutcome(kind="quit")
    if choice.kind == "new":
        return SitePickOutcome(kind="new")
    if picked.action == "toggle":
        return SitePickOutcome(kind="toggle", host=choice.host)
    return SitePickOutcome(kind="open", host=choice.host)
