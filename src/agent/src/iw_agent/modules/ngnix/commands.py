from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import Navigator, Page, PageContext, PageResult
from iw_agent.cli.interactive.selector import prompt_choice, prompt_yes_no
from iw_agent.core.actions import ActionResult

from iw_agent.cli.output import (
    DIM,
    YELLOW,
    _c,
    _reset,
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
    print_menu_item,
    print_menu_list,
    print_page_divider,
    print_page_summary,
    print_report,
    print_status_box,
    prepare_command_view,
    status_badge,
)
from iw_agent.cli.parser import add_interactive_flags, add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.actions import ActionRequest, ExecutorOptions
from iw_agent.core.commands import CommandResult
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError
from iw_agent.modules.ngnix.collector import (
    DEFAULT_NGINX_BINARY,
    DEFAULT_NGINX_TIMEOUT_SECONDS,
    certificate_paths_from_dump,
    collect_site_profiles,
    collect_virtual_hosts,
    fetch_nginx_dump,
    load_site_config_sections,
    precheck_certificate_domain,
)
from iw_agent.modules.ngnix.schemas import (
    DEFAULT_INDEX_FILES,
    TRY_FILES_SPA,
    TRY_FILES_STANDARD,
    SecurityPreset,
    SiteConfigSections,
    SiteKind,
    SiteProfile,
    SslStatus,
    VirtualHost,
)

_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$",
)


async def run_nginx(args: argparse.Namespace) -> None:
    if getattr(args, "interactive", False):
        await run_nginx_interactive(args)
        return

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
    add_interactive_flags(parser)
    add_timeout_flag(parser, default=DEFAULT_NGINX_TIMEOUT_SECONDS)
    parser.add_argument(
        "--binary",
        dest="nginx_binary",
        default=DEFAULT_NGINX_BINARY,
        help=f"nginx binary (default: {DEFAULT_NGINX_BINARY})",
    )
    parser.add_argument(
        "--certbot-dir",
        dest="certbot_live_dir",
        default="/etc/letsencrypt/live",
        help="certbot live directory for interactive SSL status",
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


_SSL_BADGES = {
    SslStatus.NO_SSL: "no SSL",
    SslStatus.SSL_OK: "HTTPS",
    SslStatus.SSL_EXPIRING: "expiring",
    SslStatus.SSL_EXPIRED: "expired",
    SslStatus.SSL_MISMATCH: "mismatch",
    SslStatus.SSL_ORPHAN: "orphan",
}


@dataclass(frozen=True)
class _MenuItem:
    kind: str
    label: str
    action_id: str | None = None
    hint: str | None = None


def _ssl_menu_item(profile: SiteProfile) -> _MenuItem | None:
    if profile.ssl_status == SslStatus.NO_SSL:
        return _MenuItem("action", "Set up HTTPS", "secure_site", "certificate needed")
    if profile.ssl_status in {SslStatus.SSL_EXPIRING, SslStatus.SSL_EXPIRED}:
        return _MenuItem("action", "Renew certificate", "renew_site")
    if profile.ssl_status == SslStatus.SSL_MISMATCH:
        return _MenuItem("action", "Fix certificate", "attach_ssl")
    return None


def _site_hub_menu(profile: SiteProfile) -> list[_MenuItem]:
    items: list[_MenuItem] = []
    ssl_item = _ssl_menu_item(profile)
    if ssl_item is not None:
        items.append(ssl_item)
    items.append(_MenuItem("configure", "Configure site", hint="domains, traffic, security"))
    if profile.virtual_host.enabled:
        items.append(_MenuItem("action", "Disable site", "disable_site"))
    else:
        items.append(_MenuItem("action", "Enable site", "enable_site"))
    items.append(_MenuItem("action", "Reload nginx", "reload"))
    items.append(_MenuItem("more", "More", hint="test, details"))
    return items


def _ssl_badge_short(profile: SiteProfile) -> str:
    return _SSL_BADGES.get(profile.ssl_status, profile.ssl_status.value)


def _base_params(context: PageContext, host: VirtualHost) -> dict:
    params = {
        "nginx_binary": context.args.nginx_binary,
        "nginx_timeout": context.args.timeout,
        "timeout": context.args.timeout,
        "certbot_live_dir": getattr(context.args, "certbot_live_dir", "/etc/letsencrypt/live"),
    }
    if host.server_names:
        params["domain"] = host.server_names[0]
    return params


async def _run_site_action(
    context: PageContext,
    profile: SiteProfile,
    action_id: str,
    params: dict,
) -> ActionResult | None:
    from iw_agent.core.actions import ActionResult

    host = profile.virtual_host
    if action_id in {"secure_site", "renew_site"}:
        if getattr(context.args, "staging", False):
            params["staging"] = True
        if not await _prompt_cert_action_params(action_id, params, host):
            return None

    request = ActionRequest(
        module="ngnix",
        action_id=action_id,
        target_id=host.config_path,
        params=params,
    )
    try:
        return await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=_site_title(host),
        )
    except ActionCancelledError:
        print("\nCancelled.")
        return None
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        return None


async def _refresh_profiles(context: PageContext) -> None:
    args = context.args
    context.data["profiles"] = await collect_site_profiles(
        nginx_binary=args.nginx_binary,
        nginx_timeout=args.timeout,
        certbot_live_dir=getattr(args, "certbot_live_dir", "/etc/letsencrypt/live"),
    )


def _valid_domain(domain: str) -> bool:
    return bool(_DOMAIN_RE.match(domain))


async def _run_create_site_action(context: PageContext, params: dict) -> bool:
    domain = str(params.get("domain", ""))
    request = ActionRequest(
        module="ngnix",
        action_id="create_site",
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
        return False
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        input("\nPress Enter to continue...")
        return False

    print()
    print_action_result(result)
    input("\nPress Enter to continue...")
    if result.ok:
        await _refresh_profiles(context)
    return result.ok


async def _run_hidden_action(
    context: PageContext,
    profile: SiteProfile,
    action_id: str,
    params: dict,
) -> bool:
    host = profile.virtual_host
    request = ActionRequest(
        module="ngnix",
        action_id=action_id,
        target_id=host.config_path,
        params=params,
    )
    try:
        result = await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=_site_title(host),
        )
    except ActionCancelledError:
        print("\nCancelled.")
        input("\nPress Enter to continue...")
        return False
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        input("\nPress Enter to continue...")
        return False

    print()
    print_action_result(result)
    input("\nPress Enter to continue...")
    return result.ok


def _on_off(value: bool) -> str:
    return "ON" if value else "OFF"


def _security_preset_label(preset: SecurityPreset) -> str:
    return {
        SecurityPreset.NONE: "None",
        SecurityPreset.BASIC: "Basic",
        SecurityPreset.STRICT: "Strict",
    }[preset]


async def _prompt_cert_action_params(action_id: str, params: dict, host: VirtualHost) -> bool:
    domain = params.get("domain") or (host.server_names[0] if host.server_names else "")
    if action_id == "secure_site":
        if not domain:
            print("Domain is required (server_name missing).", file=sys.stderr)
            input("\nPress Enter to continue...")
            return False

        errors, warnings = await precheck_certificate_domain(str(domain))
        for message in warnings:
            print(f"  warning: {message}")
        for message in errors:
            print(f"  error: {message}", file=sys.stderr)

        if errors:
            answer = input("\nPrecheck errors found. Continue anyway? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                return False
            params["force"] = True
        elif warnings:
            answer = input("\nContinue with warnings? [Y/n]: ").strip().lower()
            if answer in {"n", "no"}:
                return False

        email = input("\nLet's Encrypt email: ").strip()
        if not email:
            print("Email is required.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return False
        params["email"] = email

        if "staging" not in params:
            staging = input("Use Let's Encrypt staging (test cert)? [y/N]: ").strip().lower()
            params["staging"] = staging in {"y", "yes"}
        return True

    if action_id == "renew_site":
        if "staging" not in params:
            staging = input("\nUse Let's Encrypt staging? [y/N]: ").strip().lower()
            params["staging"] = staging in {"y", "yes"}
        return True

    return True


async def run_nginx_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    profiles = await collect_site_profiles(
        nginx_binary=args.nginx_binary,
        nginx_timeout=args.timeout,
        certbot_live_dir=getattr(args, "certbot_live_dir", "/etc/letsencrypt/live"),
    )
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(args=args, data={"profiles": profiles, "options": options})
    await Navigator(context).run(_InteractiveSiteListPage())


class _InteractiveSiteListPage(Page):
    @property
    def title(self) -> str:
        return "Sites"

    @property
    def subtitle(self) -> str:
        return "nginx"

    def render(self, context: PageContext) -> None:
        profiles: list[SiteProfile] = context.data["profiles"]
        create_index = len(profiles) + 1

        if not profiles:
            print_page_divider()
            print_menu_item(create_index, "New site")
            return

        print_page_divider()
        for index, profile in enumerate(profiles, start=1):
            host = profile.virtual_host
            name = _site_title(host)
            state = "live" if host.enabled else "off"
            ssl = _ssl_badge_short(profile)
            print_menu_item(index, name, f"{state} · {ssl}")
        print_menu_item(create_index, "New site")

    async def handle(self, context: PageContext) -> PageResult | Page:
        profiles: list[SiteProfile] = context.data["profiles"]
        create_index = len(profiles) + 1

        choice = prompt_choice(max_value=create_index, allow_back=False, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == create_index:
            return _CreateSiteWizardPage()
        return _InteractiveSiteDetailPage(profiles[choice - 1])


class _CreateSiteWizardPage(Page):
    @property
    def title(self) -> str:
        return "New site"

    @property
    def subtitle(self) -> str:
        return "nginx"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        print_page_summary("Domain → type → enable. Config is written for you.")

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

        print("\nSite type:")
        print("   1. Static files (HTML, assets)")
        print("   2. Reverse proxy (app on localhost)")
        kind_choice = prompt_choice(max_value=2, allow_back=True, allow_exit=True)
        if kind_choice is None:
            return PageResult.EXIT
        if kind_choice == -1:
            return PageResult.BACK

        params = {
            "domain": domain,
            "nginx_binary": context.args.nginx_binary,
            "nginx_timeout": context.args.timeout,
            "timeout": context.args.timeout,
            "reload": True,
            "enable_site": True,
        }

        if kind_choice == 1:
            params["site_kind"] = SiteKind.STATIC.value
            default_root = f"/var/www/{domain}"
            root = input(f"\nDocument root [{default_root}]: ").strip()
            params["document_root"] = root or default_root

            print("\ntry_files preset:")
            print(f"   1. Standard ({TRY_FILES_STANDARD})")
            print(f"   2. SPA ({TRY_FILES_SPA})")
            try_choice = prompt_choice(max_value=2, allow_back=False, allow_exit=False)
            params["try_files"] = TRY_FILES_STANDARD if try_choice == 1 else TRY_FILES_SPA
        else:
            params["site_kind"] = SiteKind.PROXY.value
            proxy_pass = input("\nBackend URL (e.g. http://127.0.0.1:3000): ").strip()
            if not proxy_pass:
                print("Backend URL is required.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            params["proxy_pass"] = proxy_pass

        params["enable_site"] = prompt_yes_no("\nEnable site now (symlink + reload)?", default=True)

        print("\nPreview:")
        print(f"  domain: {domain}")
        print(f"  type: {params['site_kind']}")
        if params["site_kind"] == SiteKind.STATIC.value:
            print(f"  root: {params.get('document_root')}")
            print(f"  try_files: {params.get('try_files')}")
        else:
            print(f"  proxy_pass: {params.get('proxy_pass')}")
        print(f"  enable: {'yes' if params['enable_site'] else 'no'}")

        if not prompt_yes_no("\nCreate this site?", default=True):
            return PageResult.STAY

        if await _run_create_site_action(context, params):
            return PageResult.BACK
        return PageResult.STAY


class _InteractiveSiteDetailPage(Page):
    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._menu = _site_hub_menu(profile)

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "nginx"

    def render(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        print_page_divider()
        ports = ", ".join(str(port) for port in host.listen_ports) or "—"
        ssl = _ssl_badge_short(self._profile)
        state = "live" if host.enabled else "off"
        print_page_summary(f"{state} · {ssl} · ports {ports}")
        if host.upstream:
            print(f"   {_c(DIM)}→ {host.upstream}{_reset()}")
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
        if entry.kind == "configure":
            return _ConfigEditorPage(self._profile)
        if entry.kind == "more":
            return _SiteMorePage(self._profile)

        result = await _run_site_action(
            context,
            self._profile,
            entry.action_id or "",
            _base_params(context, self._profile.virtual_host),
        )
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
        return PageResult.STAY


class _SiteMorePage(Page):
    _ITEMS = (
        _MenuItem("action", "Test config", "test_config"),
        _MenuItem("action", "View details", "view_details"),
    )

    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "more"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        for index, entry in enumerate(self._ITEMS, start=1):
            print_menu_item(index, entry.label)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._ITEMS), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        entry = self._ITEMS[choice - 1]
        result = await _run_site_action(
            context,
            self._profile,
            entry.action_id or "",
            _base_params(context, self._profile.virtual_host),
        )
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
        return PageResult.STAY


class _ConfigEditorPage(Page):
    _SECTIONS = (
        ("traffic", "Traffic", "proxy, paths, static files"),
        ("domain", "Domain & redirects", "names, ports, HTTPS redirects"),
        ("security", "Security", "header presets"),
    )

    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "configure"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        for index, (_key, label, hint) in enumerate(self._SECTIONS, start=1):
            print_menu_item(index, label, hint)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._SECTIONS), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        section_key = self._SECTIONS[choice - 1][0]
        if section_key == "traffic":
            return _TrafficHubPage(self._profile)
        if section_key == "domain":
            return _DomainRoutingHubPage(self._profile)
        return _SecuritySectionPage(self._profile)


class _TrafficHubPage(Page):
    _SECTIONS = (
        ("backend", "Backend"),
        ("locations", "Paths"),
        ("static", "Static files"),
    )

    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "traffic"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        for index, (_key, label) in enumerate(self._SECTIONS, start=1):
            print_menu_item(index, label)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._SECTIONS), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        section_key = self._SECTIONS[choice - 1][0]
        if section_key == "backend":
            return _BackendSectionPage(self._profile)
        if section_key == "locations":
            return _LocationsSectionPage(self._profile)
        return _StaticSectionPage(self._profile)


class _DomainRoutingHubPage(Page):
    _SECTIONS = (
        ("domain_ports", "Domain & ports"),
        ("redirects", "Redirects"),
    )

    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "domain"

    def render(self, context: PageContext) -> None:
        print_page_divider()
        for index, (_key, label) in enumerate(self._SECTIONS, start=1):
            print_menu_item(index, label)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._SECTIONS), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        section_key = self._SECTIONS[choice - 1][0]
        if section_key == "domain_ports":
            return _DomainPortsSectionPage(self._profile)
        return _RedirectsSectionPage(self._profile)


class _DomainPortsSectionPage(Page):
    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._sections: SiteConfigSections | None = None

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "domain · ports"

    async def on_enter(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        domain = host.server_names[0] if host.server_names else ""
        self._sections = await load_site_config_sections(host.config_path, domain)

    def render(self, context: PageContext) -> None:
        sections = self._sections
        if sections is None:
            return
        names = ", ".join(sections.server_names) or "—"
        listens = ", ".join(endpoint.display() for endpoint in sections.listen_endpoints) or "—"
        bind = sections.http_listen_address or "*"
        print_page_divider()
        print_page_summary(f"names {names} · listen {listens} · 443 {_on_off(sections.listen_443_ssl)}")
        print_menu_list(
            [
                (1, "Add name"),
                (2, "Remove name"),
                (3, "Toggle 443 SSL"),
                (4, "HTTP port", str(sections.http_port)),
                (5, "Bind IP", bind),
                (6, "Clear IP bind"),
            ],
        )

    async def handle(self, context: PageContext) -> PageResult | Page:
        sections = self._sections
        if sections is None:
            return PageResult.STAY

        choice = prompt_choice(max_value=6, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        params = _base_params(context, self._profile.virtual_host)
        params["reload"] = True

        if choice == 1:
            value = input("\nDomain to add (e.g. www.example.com): ").strip().lower()
            if not value:
                print("Domain is required.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            if not _valid_domain(value):
                print("Enter a valid domain name.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            params["add_server_name"] = value
        elif choice == 2:
            if len(sections.server_names) <= 1:
                print("\nCannot remove the last server_name.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            print("\nCurrent names:")
            for index, name in enumerate(sections.server_names, start=1):
                print(f"   {index}. {name}")
            pick = prompt_choice(max_value=len(sections.server_names), allow_back=False, allow_exit=False)
            params["remove_server_name"] = sections.server_names[pick - 1]
        elif choice == 3:
            if not sections.listen_443_ssl:
                has_cert = (
                    self._profile.virtual_host.ssl_enabled
                    or self._profile.certificate is not None
                )
                if not has_cert:
                    print(
                        "\nObtain HTTPS first — listen 443 ssl needs a certificate.",
                        file=sys.stderr,
                    )
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
            params["listen_443"] = not sections.listen_443_ssl
        elif choice == 4:
            raw = input(f"\nHTTP port [{sections.http_port}]: ").strip()
            if not raw:
                input("\nPress Enter to continue...")
                return PageResult.STAY
            try:
                port = int(raw)
            except ValueError:
                print("Enter a valid port number.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            if not 1 <= port <= 65535:
                print("Port must be between 1 and 65535.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            params["http_port"] = port
        elif choice == 5:
            value = input("\nIPv4 address to bind (e.g. 10.0.0.1): ").strip()
            if not value:
                print("IP address is required.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            params["http_listen_address"] = value
        else:
            params["clear_http_listen_address"] = True

        if await _run_hidden_action(context, self._profile, "apply_domain_port_settings", params):
            host = self._profile.virtual_host
            domain = host.server_names[0] if host.server_names else ""
            self._sections = await load_site_config_sections(host.config_path, domain)
        return PageResult.STAY


class _LocationsSectionPage(Page):
    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._sections: SiteConfigSections | None = None

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "traffic · paths"

    async def on_enter(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        domain = host.server_names[0] if host.server_names else ""
        self._sections = await load_site_config_sections(host.config_path, domain)

    def render(self, context: PageContext) -> None:
        sections = self._sections
        if sections is None:
            return
        print_page_divider()
        if sections.locations:
            for location in sections.locations:
                print(f"   {location.path:<10} {_c(DIM)}{location.summary()}{_reset()}")
        else:
            print_page_summary("No paths yet — add /api or /static")
        print_menu_list([(1, "Add"), (2, "Edit"), (3, "Remove")])

    async def handle(self, context: PageContext) -> PageResult | Page:
        sections = self._sections
        if sections is None:
            return PageResult.STAY

        choice = prompt_choice(max_value=3, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        params = _base_params(context, self._profile.virtual_host)
        params["reload"] = True

        if choice == 1:
            path = input("\nLocation path (e.g. /api): ").strip()
            if not path.startswith("/"):
                print("Path must start with /.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            print("\nLocation type:")
            print("   1. Reverse proxy (proxy_pass)")
            print("   2. Static root")
            print("   3. Static alias")
            kind = prompt_choice(max_value=3, allow_back=False, allow_exit=False)
            params["add_location_path"] = path
            if kind == 1:
                value = input("\nproxy_pass URL: ").strip()
                if not value:
                    print("URL is required.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["proxy_pass"] = value
            elif kind == 2:
                value = input("\nDocument root path: ").strip()
                if not value:
                    print("Path is required.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["document_root"] = value
            else:
                value = input("\nAlias path: ").strip()
                if not value:
                    print("Path is required.", file=sys.stderr)
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["alias"] = value
        elif choice == 2:
            if not sections.locations:
                print("\nNo locations to edit.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            print("\nPick location:")
            for index, location in enumerate(sections.locations, start=1):
                print(f"   {index}. {location.path} — {location.summary()}")
            pick = prompt_choice(max_value=len(sections.locations), allow_back=False, allow_exit=False)
            location = sections.locations[pick - 1]
            params["update_location_path"] = location.path
            print("\nUpdate:")
            print("   1. Set proxy_pass")
            print("   2. Set root")
            print("   3. Set alias")
            print("   4. Set try_files")
            print("   5. Remove proxy_pass")
            update_choice = prompt_choice(max_value=5, allow_back=False, allow_exit=False)
            if update_choice == 1:
                value = input("\nproxy_pass URL: ").strip()
                if not value:
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["proxy_pass"] = value
            elif update_choice == 2:
                value = input("\nDocument root path: ").strip()
                if not value:
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["document_root"] = value
            elif update_choice == 3:
                value = input("\nAlias path: ").strip()
                if not value:
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["alias"] = value
            elif update_choice == 4:
                value = input("\ntry_files (e.g. $uri $uri/ =404): ").strip()
                if not value:
                    input("\nPress Enter to continue...")
                    return PageResult.STAY
                params["try_files"] = value
            else:
                params["remove_proxy"] = True
        else:
            if not sections.locations:
                print("\nNo locations to remove.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            print("\nPick location to remove:")
            for index, location in enumerate(sections.locations, start=1):
                print(f"   {index}. {location.path} — {location.summary()}")
            pick = prompt_choice(max_value=len(sections.locations), allow_back=False, allow_exit=False)
            params["remove_location_path"] = sections.locations[pick - 1].path

        if await _run_hidden_action(context, self._profile, "apply_location_settings", params):
            host = self._profile.virtual_host
            domain = host.server_names[0] if host.server_names else ""
            self._sections = await load_site_config_sections(host.config_path, domain)
        return PageResult.STAY


class _RedirectsSectionPage(Page):
    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._sections: SiteConfigSections | None = None

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "domain · redirects"

    async def on_enter(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        domain = host.server_names[0] if host.server_names else ""
        self._sections = await load_site_config_sections(host.config_path, domain)

    def render(self, context: PageContext) -> None:
        sections = self._sections
        if sections is None:
            return
        print_page_divider()
        print_page_summary(
            f"HTTP→HTTPS {_on_off(sections.http_to_https)} · www→apex {_on_off(sections.www_to_apex)}",
        )
        print_menu_list([(1, "Toggle HTTP→HTTPS"), (2, "Toggle www→apex")])

    async def handle(self, context: PageContext) -> PageResult | Page:
        sections = self._sections
        if sections is None:
            return PageResult.STAY

        choice = prompt_choice(max_value=2, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        params = _base_params(context, self._profile.virtual_host)
        params["reload"] = True
        if choice == 1:
            params["http_to_https"] = not sections.http_to_https
        else:
            params["www_to_apex"] = not sections.www_to_apex

        if await _run_hidden_action(context, self._profile, "apply_redirect_settings", params):
            host = self._profile.virtual_host
            domain = host.server_names[0] if host.server_names else ""
            self._sections = await load_site_config_sections(host.config_path, domain)
        return PageResult.STAY


class _BackendSectionPage(Page):
    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._sections: SiteConfigSections | None = None

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "traffic · backend"

    async def on_enter(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        domain = host.server_names[0] if host.server_names else ""
        self._sections = await load_site_config_sections(host.config_path, domain)

    def render(self, context: PageContext) -> None:
        sections = self._sections
        if sections is None:
            return
        print_page_divider()
        print_page_summary(f"proxy_pass {sections.proxy_pass or '—'}")
        print_menu_list([(1, "Set URL"), (2, "Remove")])

    async def handle(self, context: PageContext) -> PageResult | Page:
        sections = self._sections
        if sections is None:
            return PageResult.STAY

        choice = prompt_choice(max_value=2, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        params = _base_params(context, self._profile.virtual_host)
        params["reload"] = True

        if choice == 1:
            value = input("\nproxy_pass URL (e.g. http://127.0.0.1:3000): ").strip()
            if not value:
                print("URL is required.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            params["proxy_pass"] = value
        else:
            params["remove_proxy"] = True

        if await _run_hidden_action(context, self._profile, "apply_backend_settings", params):
            host = self._profile.virtual_host
            domain = host.server_names[0] if host.server_names else ""
            self._sections = await load_site_config_sections(host.config_path, domain)
        return PageResult.STAY


class _StaticSectionPage(Page):
    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._sections: SiteConfigSections | None = None

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "traffic · static"

    async def on_enter(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        domain = host.server_names[0] if host.server_names else ""
        self._sections = await load_site_config_sections(host.config_path, domain)

    def render(self, context: PageContext) -> None:
        sections = self._sections
        if sections is None:
            return
        print_page_divider()
        print_page_summary(
            f"root {sections.document_root or '—'} · try_files {sections.try_files or '—'}",
        )
        print_menu_list(
            [
                (1, "Set root"),
                (2, "Set index"),
                (3, "try_files standard"),
                (4, "try_files SPA"),
                (5, "Remove try_files"),
            ],
        )

    async def handle(self, context: PageContext) -> PageResult | Page:
        sections = self._sections
        if sections is None:
            return PageResult.STAY

        choice = prompt_choice(max_value=5, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        params = _base_params(context, self._profile.virtual_host)
        params["reload"] = True

        if choice == 1:
            value = input("\nDocument root path (e.g. /var/www/html): ").strip()
            if not value:
                print("Path is required.", file=sys.stderr)
                input("\nPress Enter to continue...")
                return PageResult.STAY
            params["document_root"] = value
        elif choice == 2:
            current = sections.index_files or DEFAULT_INDEX_FILES
            value = input(f"\nIndex files [{current}]: ").strip()
            params["index_files"] = value or current
        elif choice == 3:
            params["try_files"] = TRY_FILES_STANDARD
        elif choice == 4:
            params["try_files"] = TRY_FILES_SPA
        else:
            params["remove_try_files"] = True

        if await _run_hidden_action(context, self._profile, "apply_static_settings", params):
            host = self._profile.virtual_host
            domain = host.server_names[0] if host.server_names else ""
            self._sections = await load_site_config_sections(host.config_path, domain)
        return PageResult.STAY


class _SecuritySectionPage(Page):
    _PRESETS = (
        SecurityPreset.BASIC,
        SecurityPreset.STRICT,
        SecurityPreset.NONE,
    )

    def __init__(self, profile: SiteProfile) -> None:
        self._profile = profile
        self._sections: SiteConfigSections | None = None

    @property
    def title(self) -> str:
        return _site_title(self._profile.virtual_host)

    @property
    def subtitle(self) -> str:
        return "security"

    async def on_enter(self, context: PageContext) -> None:
        host = self._profile.virtual_host
        domain = host.server_names[0] if host.server_names else ""
        self._sections = await load_site_config_sections(host.config_path, domain)

    def render(self, context: PageContext) -> None:
        sections = self._sections
        if sections is None:
            return
        current = _security_preset_label(sections.security_preset)
        print_page_divider()
        print_page_summary(f"preset {current}")
        if not self._profile.virtual_host.ssl_enabled:
            print(f"   {_c(YELLOW)}Strict needs HTTPS first{_reset()}")
        print_menu_list([(1, "Basic"), (2, "Strict"), (3, "None")])

    async def handle(self, context: PageContext) -> PageResult | Page:
        sections = self._sections
        if sections is None:
            return PageResult.STAY

        choice = prompt_choice(max_value=3, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        preset = self._PRESETS[choice - 1]
        if preset is SecurityPreset.STRICT and not self._profile.virtual_host.ssl_enabled:
            print("\nStrict preset requires HTTPS on this site.", file=sys.stderr)
            input("\nPress Enter to continue...")
            return PageResult.STAY

        params = _base_params(context, self._profile.virtual_host)
        params["reload"] = True
        params["security_preset"] = preset.value

        if await _run_hidden_action(context, self._profile, "apply_security_settings", params):
            host = self._profile.virtual_host
            domain = host.server_names[0] if host.server_names else ""
            self._sections = await load_site_config_sections(host.config_path, domain)
        return PageResult.STAY
