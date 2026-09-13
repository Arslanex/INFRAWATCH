from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import PageContext
from iw_agent.cli.interactive.selector import prompt_choice, prompt_yes_no
from iw_agent.core.actions import ActionResult
from iw_agent.core.executor_runtime import has_effective_root

from iw_agent.cli.output import (
    DIM,
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
    clear_screen,
    print_empty,
    print_group_heading,
    print_info_box,
    print_insight,
    print_menu_item,
    print_page_divider,
    print_page_header,
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
from iw_agent.modules.nginx.collector import (
    DEFAULT_NGINX_BINARY,
    DEFAULT_NGINX_TIMEOUT_SECONDS,
    certificate_paths_from_dump,
    collect_site_profiles,
    collect_virtual_hosts,
    fetch_nginx_dump,
    precheck_certificate_domain,
)
from iw_agent.modules.nginx.schemas import (
    TRY_FILES_SPA,
    TRY_FILES_STANDARD,
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


async def run_nginx_editor(args: argparse.Namespace) -> None:
    """Open one site config in the structural editor."""
    prepare_command_view(plain=getattr(args, "plain", False))
    virtual_hosts = await collect_virtual_hosts(
        nginx_binary=args.nginx_binary,
        timeout=args.timeout,
    )
    host = _pick_site_for_editor(virtual_hosts, getattr(args, "site", None))
    if host is not None:
        await _open_editor(args, host)


async def _open_editor(args: argparse.Namespace, host: VirtualHost) -> None:
    from iw_agent.modules.nginx.confparse import is_lossless
    from iw_agent.modules.nginx.editor.app import (
        EditorUnavailable,
        load_session,
        run_editor,
    )

    text = Path(host.config_path).read_text(encoding="utf-8", errors="replace")
    if not is_lossless(text):
        # the parser is what would rewrite this file; if it cannot reproduce
        # the original byte for byte, it has no business editing it
        print(
            f"error: {host.config_path} cannot be parsed safely — "
            "refusing to open it for editing",
            file=sys.stderr,
        )
        input("\nPress Enter to continue...")
        return

    dry_run = getattr(args, "dry_run", False)
    session = load_session(
        host.config_path,
        title=host.server_names[0] if host.server_names else Path(host.config_path).name,
        read_only=not has_effective_root() and not dry_run,
        dry_run=dry_run,
        action_params={
            "nginx_binary": args.nginx_binary,
            "timeout": args.timeout,
            "certbot_live_dir": getattr(args, "certbot_live_dir", "/etc/letsencrypt/live"),
            "staging": getattr(args, "staging", False),
        },
    )
    try:
        await run_editor(session)
    except EditorUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)


def _pick_site_for_editor(virtual_hosts, wanted):
    if not virtual_hosts:
        print("no nginx sites found", file=sys.stderr)
        return None

    if wanted:
        for host in virtual_hosts:
            if wanted in host.server_names or host.config_path == wanted:
                return host
        print(f"no site matching {wanted!r}", file=sys.stderr)
        return None

    if len(virtual_hosts) == 1:
        return virtual_hosts[0]

    print_page_header("Sites", "nginx")
    for index, host in enumerate(virtual_hosts, start=1):
        print_menu_item(index, _site_title(host), host.config_path)
    choice = prompt_choice(max_value=len(virtual_hosts), allow_exit=True)
    if choice is None:
        return None
    return virtual_hosts[choice - 1]


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
    parser.add_argument(
        "--site",
        default=None,
        help="with -i, open this site directly instead of listing (domain or config path)",
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
        module="nginx",
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


def _www_domain(domain: str) -> str:
    return f"www.{domain}"


def _build_server_names(domain: str, *, include_www: bool, extra_domains: list[str]) -> list[str]:
    names = [domain]
    if include_www:
        www = _www_domain(domain)
        if www not in names:
            names.append(www)
    for extra in extra_domains:
        if extra and extra not in names:
            names.append(extra)
    return names


def _parse_extra_domains(raw: str) -> tuple[list[str], str | None]:
    if not raw.strip():
        return [], None
    extras: list[str] = []
    for token in raw.replace(",", " ").split():
        value = token.strip().lower()
        if not value:
            continue
        if not _valid_domain(value):
            return [], f"invalid domain: {value}"
        if value not in extras:
            extras.append(value)
    return extras, None


def _find_profile_by_domain(context: PageContext, domain: str) -> SiteProfile | None:
    for profile in context.data["profiles"]:
        host = profile.virtual_host
        if domain in host.server_names:
            return profile
        if host.config_path.endswith(f"/{domain}"):
            return profile
    return None


async def _run_create_site_action(
    context: PageContext,
    params: dict,
    *,
    pause: bool = True,
) -> bool:
    domain = str(params.get("domain", ""))
    request = ActionRequest(
        module="nginx",
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
        if pause:
            input("\nPress Enter to continue...")
        return False
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        if pause:
            input("\nPress Enter to continue...")
        return False

    if pause:
        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
    if result.ok:
        await _refresh_profiles(context)
    return result.ok


async def _run_create_site_with_optional_https(
    context: PageContext,
    params: dict,
    *,
    pause: bool = True,
) -> bool:
    https_now = bool(params.pop("https_now", False))
    email = params.pop("email", None)
    staging = bool(params.pop("staging", False))

    if not await _run_create_site_action(context, params, pause=pause):
        return False

    if not https_now:
        return True

    if not email:
        print("HTTPS setup skipped — email was not provided.", file=sys.stderr)
        return True

    domain = str(params.get("domain", ""))
    profile = _find_profile_by_domain(context, domain)
    if profile is None:
        print(
            "Site created but could not find it for HTTPS setup. "
            "Use Obtain HTTPS from the editor actions panel (x).",
            file=sys.stderr,
        )
        return True

    secure_params = _base_params(context, profile.virtual_host)
    secure_params["email"] = email
    secure_params["staging"] = staging or getattr(context.args, "staging", False)
    secure_params["force"] = bool(params.get("force", False))

    result = await _run_site_action(context, profile, "secure_site", secure_params)
    if result is None:
        return True
    if pause:
        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
    if result.ok:
        await _refresh_profiles(context)
    return result.ok


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

        if not params.get("email"):
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
    if getattr(args, "site", None):
        await run_nginx_editor(args)
        return

    prepare_command_view(plain=args.plain)
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))

    while True:
        profiles = await collect_site_profiles(
            nginx_binary=args.nginx_binary,
            nginx_timeout=args.timeout,
            certbot_live_dir=getattr(args, "certbot_live_dir", "/etc/letsencrypt/live"),
        )
        picked = await _interactive_pick_site(args, profiles)
        if picked is None:
            break
        if picked == "__new__":
            host = await _interactive_create_site(args, profiles, options)
            if host is not None:
                await _open_editor(args, host)
            continue
        await _open_editor(args, picked)


async def _interactive_pick_site(
    args: argparse.Namespace,
    profiles: list[SiteProfile],
) -> VirtualHost | str | None:
    """Return a host to edit, ``__new__``, or ``None`` to quit."""
    create_index = len(profiles) + 1
    quit_index = create_index + 1 if profiles else 2

    clear_screen()
    print_page_header("Sites", "nginx")
    print_page_divider()

    if not profiles:
        print_page_summary("No sites yet — create one or quit.")
        print_menu_item(1, "New site", "minimal skeleton, then open the editor")
        print_menu_item(2, "Quit")
        choice = prompt_choice(max_value=2, allow_back=False, allow_exit=True)
        if choice is None or choice == 2:
            return None
        return "__new__"

    for index, profile in enumerate(profiles, start=1):
        host = profile.virtual_host
        state = "live" if host.enabled else "off"
        ssl = _ssl_badge_short(profile)
        print_menu_item(index, _site_title(host), f"{state} · {ssl} · {host.config_path}")
    print_menu_item(create_index, "New site", "create skeleton, then edit in place")
    print_menu_item(quit_index, "Quit")

    choice = prompt_choice(max_value=quit_index, allow_back=False, allow_exit=True)
    if choice is None or choice == quit_index:
        return None
    if choice == create_index:
        return "__new__"
    return profiles[choice - 1].virtual_host


async def _interactive_create_site(
    args: argparse.Namespace,
    profiles: list[SiteProfile],
    options: ExecutorOptions,
) -> VirtualHost | None:
    context = PageContext(args=args, data={"profiles": profiles, "options": options})
    domain = input("\nDomain (e.g. app.example.com): ").strip().lower()
    if not domain:
        print("Domain is required.", file=sys.stderr)
        return None
    if not _valid_domain(domain):
        print("Enter a valid domain name.", file=sys.stderr)
        return None

    include_www = prompt_yes_no(f"\nAlso serve www.{domain}?", default=True)
    extra_raw = input(
        "\nExtra domains (comma-separated, or leave empty): ",
    ).strip()
    extra_domains, extra_error = _parse_extra_domains(extra_raw)
    if extra_error:
        print(extra_error, file=sys.stderr)
        return None

    server_names = _build_server_names(
        domain,
        include_www=include_www,
        extra_domains=extra_domains,
    )

    print("\nHTTP listen port:")
    print("   1. Standard (80)")
    print("   2. Custom port")
    port_choice = prompt_choice(max_value=2, allow_back=False, allow_exit=True)
    if port_choice is None:
        return None
    http_port = 80
    if port_choice == 2:
        raw_port = input("\nCustom HTTP port (e.g. 8080): ").strip()
        try:
            http_port = int(raw_port)
        except ValueError:
            print("Enter a valid port number.", file=sys.stderr)
            return None
        if http_port < 1 or http_port > 65535:
            print("Port must be between 1 and 65535.", file=sys.stderr)
            return None

    print("\nSite type:")
    print("   1. Static files (HTML, assets)")
    print("   2. Reverse proxy (app on localhost)")
    kind_choice = prompt_choice(max_value=2, allow_back=True, allow_exit=True)
    if kind_choice is None or kind_choice == -1:
        return None

    params = {
        "domain": domain,
        "server_names": server_names,
        "http_port": http_port,
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
            return None
        params["proxy_pass"] = proxy_pass

    params["enable_site"] = prompt_yes_no("\nEnable site now (symlink + reload)?", default=True)

    https_now = False
    email = ""
    staging = getattr(context.args, "staging", False)
    if params["enable_site"]:
        https_now = prompt_yes_no(
            "\nSet up HTTPS now (certbot + nginx SSL + redirect)?",
            default=False,
        )
        if https_now:
            email = input("\nLet's Encrypt email: ").strip()
            if not email:
                print("Email is required for HTTPS setup.", file=sys.stderr)
                return None
            if not staging:
                staging = prompt_yes_no(
                    "Use Let's Encrypt staging (test cert)?",
                    default=False,
                )

            errors, warnings = await precheck_certificate_domain(domain)
            for message in warnings:
                print(f"  warning: {message}")
            for message in errors:
                print(f"  error: {message}", file=sys.stderr)
            if errors:
                if not prompt_yes_no("\nPrecheck errors found. Continue anyway?", default=False):
                    return None
                params["force"] = True
            elif warnings:
                if not prompt_yes_no("\nContinue with warnings?", default=True):
                    return None

    print("\nPreview:")
    print(f"  domain: {domain}")
    print(f"  server_names: {', '.join(server_names)}")
    print(f"  http_port: {http_port}")
    print(f"  type: {params['site_kind']}")
    if params["site_kind"] == SiteKind.STATIC.value:
        print(f"  root: {params.get('document_root')}")
        print(f"  try_files: {params.get('try_files')}")
    else:
        print(f"  proxy_pass: {params.get('proxy_pass')}")
    print(f"  enable: {'yes' if params['enable_site'] else 'no'}")
    print(f"  https_now: {'yes' if https_now else 'no'}")
    if https_now:
        print(f"  email: {email}")
        print(f"  staging: {'yes' if staging else 'no'}")

    if not prompt_yes_no("\nCreate this site?", default=True):
        return None

    create_params = {
        **params,
        "https_now": https_now,
        "email": email,
        "staging": staging,
    }
    if not await _run_create_site_with_optional_https(context, create_params, pause=False):
        return None

    await _refresh_profiles(context)
    profile = _find_profile_by_domain(context, domain)
    if profile is not None:
        return profile.virtual_host

    from iw_agent.modules.nginx.collector import DEFAULT_SITES_AVAILABLE_DIR

    config_path = str(Path(DEFAULT_SITES_AVAILABLE_DIR) / domain)
    return VirtualHost(config_path=config_path, server_names=server_names, enabled=True)
