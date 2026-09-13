from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import Navigator, Page, PageContext, PageResult
from iw_agent.cli.interactive.selector import prompt_choice, prompt_yes_no
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
    print_menu_item,
    print_page_divider,
    print_page_summary,
    print_report,
    print_status_box,
    prepare_command_view,
)
from iw_agent.cli.parser import add_interactive_flags
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError
from iw_agent.modules.ssl.collector import (
    DEFAULT_CERTBOT_LIVE_DIR,
    cert_name_from_path,
    collect_certificates,
)
from iw_agent.modules.ssl.schemas import Certificate

_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
)


async def run_certs(args: argparse.Namespace) -> None:
    if getattr(args, "interactive", False):
        await run_certs_interactive(args)
        return

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


def _expiry_days(certificate: Certificate) -> int | None:
    if certificate.not_after is None:
        return None
    expiry = (
        certificate.not_after
        if certificate.not_after.tzinfo
        else certificate.not_after.replace(tzinfo=timezone.utc)
    )
    now = datetime.now(timezone.utc)
    return (expiry - now).days


def _expiring_alert(certificates: list[Certificate]) -> str:
    expired = sum(1 for cert in certificates if (_expiry_days(cert) or 0) < 0)
    expiring = sum(
        1
        for cert in certificates
        if (_expiry_days(cert) is not None and 0 <= _expiry_days(cert) <= 30)
    )
    if expired:
        return f"{expired} certificate(s) expired — renew immediately"
    if expiring:
        return f"{expiring} certificate(s) expiring within 30 days"
    return ""


def _ordered_certificates(certificates: list[Certificate]) -> list[Certificate]:
    def sort_key(certificate: Certificate) -> tuple[int, int, str]:
        _badge, _status, _text, _bar, tone = cert_expiry_details(certificate.not_after)
        tone_rank = {"bad": 0, "warn": 1, "ok": 2, "off": 3}.get(tone, 3)
        days = _expiry_days(certificate)
        day_rank = days if days is not None else 9999
        return (tone_rank, day_rank, certificate.domain.lower())

    return sorted(certificates, key=sort_key)


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
    add_interactive_flags(parser)
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


def _cert_list_hint(certificate: Certificate) -> str:
    _badge, status, expiry_text, _bar, tone = cert_expiry_details(certificate.not_after)
    parts = [status.lower(), expiry_text.split("(")[0].strip(), certificate.source]
    if tone == "bad":
        parts.insert(0, "renew now")
    return " · ".join(part for part in parts if part)


def _is_certbot_certificate(certificate: Certificate) -> bool:
    return certificate.source == "certbot"


def _cert_params(context: PageContext, certificate: Certificate) -> dict:
    return {
        "certbot_live_dir": context.args.certbot_live_dir,
        "cert_name": cert_name_from_path(certificate.cert_path),
        "staging": getattr(context.args, "staging", False),
        "timeout": 120.0,
    }


@dataclass(frozen=True)
class _HubEntry:
    label: str
    hint: str = ""
    action_id: str = ""
    kind: str = "action"


def _cert_hub_menu(certificate: Certificate) -> list[_HubEntry]:
    menu: list[_HubEntry] = []
    _badge, status, _text, _bar, tone = cert_expiry_details(certificate.not_after)

    if _is_certbot_certificate(certificate):
        renew_hint = "certbot renew --cert-name"
        if tone in {"bad", "warn"}:
            renew_hint = f"{status.lower()} — renew with certbot"
        menu.append(_HubEntry("Renew certificate", renew_hint, "renew_certificate"))

    menu.extend(
        [
            _HubEntry("View details", "domain, issuer, expiry, path", "view_certificate"),
            _HubEntry("More", "file path and validity window"),
        ]
    )
    return menu


async def _refresh_certificates(context: PageContext) -> None:
    args = context.args
    certificates = await collect_certificates(
        certbot_live_dir=args.certbot_live_dir,
        nginx_cert_paths=args.nginx_paths,
    )
    context.data["certificates"] = _ordered_certificates(certificates)


async def _run_cert_action(
    context: PageContext,
    certificate: Certificate,
    action_id: str,
    *,
    params: dict | None = None,
) -> ActionResult | None:
    request = ActionRequest(
        module="ssl",
        action_id=action_id,
        target_id=certificate.cert_path,
        params=params or _cert_params(context, certificate),
    )
    try:
        return await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=certificate.domain,
        )
    except ActionCancelledError:
        print("\nCancelled.")
        return None
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        return None


async def _prompt_renew_params(context: PageContext, params: dict) -> bool:
    if getattr(context.args, "staging", False):
        params["staging"] = True
        return True
    if "staging" not in params:
        staging = input("\nUse Let's Encrypt staging? [y/N]: ").strip().lower()
        params["staging"] = staging in {"y", "yes"}
    return True


def _valid_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.match(domain))


async def run_certs_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    certificates = _ordered_certificates(
        await collect_certificates(
            certbot_live_dir=args.certbot_live_dir,
            nginx_cert_paths=args.nginx_paths,
        )
    )
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"certificates": certificates, "options": options},
    )
    await Navigator(context).run(_InteractiveCertListPage())


class _InteractiveCertListPage(Page):
    @property
    def title(self) -> str:
        return "Certificates"

    @property
    def subtitle(self) -> str:
        return "ssl"

    def render(self, context: PageContext) -> None:
        certificates: list[Certificate] = context.data["certificates"]
        obtain_index = len(certificates) + 1
        print_page_divider()

        alert = _expiring_alert(certificates)
        if alert:
            print_page_summary(alert)
            print_page_divider()

        if not certificates:
            print_page_summary("No certificates found on disk.")
            print_menu_item(obtain_index, "Obtain new certificate")
            return

        for index, certificate in enumerate(certificates, start=1):
            print_menu_item(index, certificate.domain, _cert_list_hint(certificate))
        print_menu_item(obtain_index, "Obtain new certificate")

    async def handle(self, context: PageContext) -> PageResult | Page:
        certificates: list[Certificate] = context.data["certificates"]
        obtain_index = len(certificates) + 1

        choice = prompt_choice(max_value=obtain_index, allow_back=False, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == obtain_index:
            return _ObtainCertificateWizardPage()
        return _InteractiveCertDetailPage(certificates[choice - 1])


class _InteractiveCertDetailPage(Page):
    def __init__(self, certificate: Certificate) -> None:
        self._certificate = certificate
        self._menu = _cert_hub_menu(certificate)

    @property
    def title(self) -> str:
        return self._certificate.domain

    @property
    def subtitle(self) -> str:
        return "ssl"

    def render(self, context: PageContext) -> None:
        certificate = self._certificate
        _badge, _status, expiry_text, bar_percent, tone = cert_expiry_details(
            certificate.not_after,
        )
        print_page_divider()
        print_page_summary(_cert_list_hint(certificate))
        print(f"   {format_meter('Left', bar_percent)}")
        print(f"   issuer: {format_optional(certificate.issuer, fallback='unknown')}")
        print_page_divider()
        for index, entry in enumerate(self._menu, start=1):
            print_menu_item(index, entry.label, entry.hint)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._menu), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        entry = self._menu[choice - 1]
        if entry.kind == "more" or not entry.action_id:
            return _CertMorePage(self._certificate)

        params = _cert_params(context, self._certificate)
        if entry.action_id == "renew_certificate":
            if not await _prompt_renew_params(context, params):
                return PageResult.STAY

        result = await _run_cert_action(
            context,
            self._certificate,
            entry.action_id,
            params=params,
        )
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        if entry.action_id == "view_certificate":
            print(result.message)
        else:
            print_action_result(result)
        input("\nPress Enter to continue...")

        if result.ok and entry.action_id == "renew_certificate":
            await _refresh_certificates(context)
            refreshed = next(
                (
                    cert
                    for cert in context.data["certificates"]
                    if cert.cert_path == self._certificate.cert_path
                ),
                self._certificate,
            )
            self._certificate = refreshed
            self._menu = _cert_hub_menu(refreshed)
        return PageResult.STAY


class _CertMorePage(Page):
    def __init__(self, certificate: Certificate) -> None:
        self._certificate = certificate

    @property
    def title(self) -> str:
        return self._certificate.domain

    @property
    def subtitle(self) -> str:
        return "ssl · more"

    def render(self, context: PageContext) -> None:
        certificate = self._certificate
        print_page_divider()
        print_page_summary(certificate.source)
        if certificate.not_before:
            print(f"\n   Valid from: {certificate.not_before.strftime('%Y-%m-%d')}")
        if certificate.not_after:
            print(f"   Valid until: {certificate.not_after.strftime('%Y-%m-%d')}")
        print(f"\n   File: {certificate.cert_path}")
        if _is_certbot_certificate(certificate):
            print(f"   Cert name: {cert_name_from_path(certificate.cert_path)}")
        print_page_divider()
        print_menu_item(1, "View details")

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=1, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        result = await _run_cert_action(context, self._certificate, "view_certificate")
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print(result.message)
        input("\nPress Enter to continue...")
        return PageResult.STAY


class _ObtainCertificateWizardPage(Page):
    @property
    def title(self) -> str:
        return "Obtain certificate"

    @property
    def subtitle(self) -> str:
        return "ssl"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        print_page_summary("Domain → email → certbot certonly (nginx or webroot).")

    async def handle(self, context: PageContext) -> PageResult | Page:
        domain = input("\nDomain (e.g. app.example.com): ").strip().lower()
        if not domain:
            print("Domain is required.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY
        if not _valid_domain(domain):
            print("Enter a valid domain name.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY

        email = input("\nLet's Encrypt email: ").strip()
        if not email:
            print("Email is required.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY

        staging = prompt_yes_no("Use Let's Encrypt staging (test cert)?", default=False)
        params = {
            "domain": domain,
            "email": email,
            "staging": staging or getattr(context.args, "staging", False),
            "method": "auto",
            "certbot_live_dir": context.args.certbot_live_dir,
            "timeout": 120.0,
        }

        print("\nPreview:")
        print(f"  domain: {domain}")
        print(f"  email: {email}")
        print(f"  staging: {'yes' if params['staging'] else 'no'}")

        if not prompt_yes_no("\nObtain this certificate?", default=True):
            return PageResult.STAY

        request = ActionRequest(
            module="ssl",
            action_id="obtain_certificate",
            target_id=domain,
            params=params,
        )
        try:
            result = await run_action_with_prompts(
                request,
                options=context.data["options"],
                target_label=domain,
            )
        except ActionCancelledError:
            print("\nCancelled.")
            input("\nPress Enter to continue...")
            return PageResult.STAY
        except ActionDeniedError as exc:
            print(f"\n{exc.message}")
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
        if result.ok:
            await _refresh_certificates(context)
            live_path = str(
                Path(context.args.certbot_live_dir) / domain / "fullchain.pem",
            )
            refreshed = next(
                (
                    cert
                    for cert in context.data["certificates"]
                    if cert.cert_path == live_path or cert.domain == domain
                ),
                None,
            )
            if refreshed is not None:
                return _InteractiveCertDetailPage(refreshed)
            return PageResult.BACK
        return PageResult.STAY


COMMAND_SPECS = [
    CliCommandSpec("certs", "ssl certificates on disk", run_certs, _configure),
]
