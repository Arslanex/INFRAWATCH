from __future__ import annotations

import re
from dataclasses import dataclass

from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.commands import CommandResult, is_command_available, run_command
from iw_agent.modules.ssl.collector import DEFAULT_CERTBOT_LIVE_DIR, collect_certificates

MODULE = "ssl"
DEFAULT_WEBROOT = "/var/www/html"
_CERTBOT_NGINX_PLUGIN = re.compile(r"^\* nginx", re.MULTILINE)

SSL_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="view_certificate",
        label="View certificate details",
        kind=ActionKind.READ,
        description="Show parsed certificate fields from collector data",
    ),
    ActionSpec(
        id="renew_certificate",
        label="Renew certificate",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Run certbot renew --cert-name for one certificate",
    ),
    ActionSpec(
        id="obtain_certificate",
        label="Obtain certificate",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Run certbot certonly (nginx plugin or webroot)",
    ),
)

SSL_ACTIONS_BY_ID = {action.id: action for action in SSL_ACTIONS}


@dataclass(frozen=True)
class CertbotRequest:
    domain: str
    email: str
    method: str = "auto"
    webroot: str = DEFAULT_WEBROOT
    staging: bool = False
    certbot_binary: str = "certbot"
    timeout: float = 120.0


@dataclass(frozen=True)
class SslExecutorConfig:
    certbot_live_dir: str = DEFAULT_CERTBOT_LIVE_DIR
    certbot_binary: str = "certbot"
    timeout: float = 120.0

    @classmethod
    def from_params(cls, params: dict) -> SslExecutorConfig:
        values = {
            key: params[key]
            for key in ("certbot_live_dir", "certbot_binary", "timeout", "certbot_timeout")
            if key in params
        }
        if "certbot_timeout" in values and "timeout" not in values:
            values["timeout"] = values.pop("certbot_timeout")
        return cls(**values)


class SslExecutor:
    module = MODULE

    def actions(self):
        return SSL_ACTIONS

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        if request.action_id not in SSL_ACTIONS_BY_ID:
            return _fail(request, f"unknown ssl action: {request.action_id}", options)

        config = SslExecutorConfig.from_params(request.params)
        handler = _HANDLERS.get(request.action_id)
        if handler is None:
            return _fail(request, f"handler missing for {request.action_id}", options)
        return await handler(request, options, config=config)


def cert_paths_for_domain(domain: str, live_dir: str = "/etc/letsencrypt/live") -> tuple[str, str]:
    base = f"{live_dir.rstrip('/')}/{domain}"
    return f"{base}/fullchain.pem", f"{base}/privkey.pem"


def resolve_challenge_method(method: str, certbot_binary: str = "certbot") -> str:
    if method in {"nginx", "webroot", "standalone"}:
        return method
    if nginx_plugin_available(certbot_binary):
        return "nginx"
    return "webroot"


def nginx_plugin_available(certbot_binary: str = "certbot") -> bool:
    if not is_command_available(certbot_binary):
        return False
    try:
        import subprocess

        completed = subprocess.run(
            [certbot_binary, "plugins"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(_CERTBOT_NGINX_PLUGIN.search(completed.stdout))


def build_obtain_argv(request: CertbotRequest) -> list[str]:
    method = resolve_challenge_method(request.method, request.certbot_binary)
    argv = [
        request.certbot_binary,
        "certonly",
        "--non-interactive",
        "--agree-tos",
        "-m",
        request.email,
        "-d",
        request.domain,
    ]
    if request.staging:
        argv.append("--staging")
    if method == "nginx":
        argv.append("--nginx")
    elif method == "standalone":
        argv.append("--standalone")
    else:
        argv.extend(["--webroot", "-w", request.webroot])
    return argv


def build_renew_argv(
    cert_name: str,
    *,
    certbot_binary: str = "certbot",
    staging: bool = False,
    dry_run: bool = False,
) -> list[str]:
    argv = [certbot_binary, "renew", "--cert-name", cert_name, "--non-interactive"]
    if staging:
        argv.append("--staging")
    if dry_run:
        argv.append("--dry-run")
    return argv


async def obtain_certificate(
    request: CertbotRequest,
    *,
    dry_run: bool = False,
) -> tuple[list[str], CommandResult | None]:
    argv = build_obtain_argv(request)
    if dry_run:
        return argv, None
    if not is_command_available(request.certbot_binary):
        raise RuntimeError(f"{request.certbot_binary} is not installed")
    result = await run_command(argv, timeout=request.timeout)
    return argv, result


async def renew_certificate(
    cert_name: str,
    *,
    certbot_binary: str = "certbot",
    timeout: float = 120.0,
    staging: bool = False,
    dry_run: bool = False,
) -> tuple[list[str], CommandResult | None]:
    argv = build_renew_argv(
        cert_name,
        certbot_binary=certbot_binary,
        staging=staging,
        dry_run=dry_run,
    )
    if dry_run:
        return argv, None
    if not is_command_available(certbot_binary):
        raise RuntimeError(f"{certbot_binary} is not installed")
    result = await run_command(argv, timeout=timeout)
    return argv, result


def _fail(request: ActionRequest, message: str, options: ExecutorOptions) -> ActionResult:
    return ActionResult(
        ok=False,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


async def _view_certificate(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: SslExecutorConfig,
) -> ActionResult:
    cert_path = request.target_id
    if not cert_path:
        return _fail(request, "target_id must be a certificate path", options)

    certificates = await collect_certificates(
        certbot_live_dir=config.certbot_live_dir,
        nginx_cert_paths=[cert_path],
    )
    match = next((cert for cert in certificates if cert.cert_path == cert_path), None)
    if match is None:
        return _fail(request, f"certificate not readable: {cert_path}", options)

    expiry = match.not_after.isoformat() if match.not_after else "-"
    message = (
        f"domain={match.domain}\n"
        f"issuer={match.issuer or '-'}\n"
        f"expires={expiry}\n"
        f"source={match.source}\n"
        f"path={match.cert_path}"
    )
    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=message,
    )


async def _obtain_certificate(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: SslExecutorConfig,
) -> ActionResult:
    domain = str(request.params.get("domain") or request.target_id or "")
    email = request.params.get("email")
    if not domain:
        return _fail(request, "domain is required", options)
    if not email:
        return _fail(request, "email is required for certbot obtain", options)

    certbot_request = CertbotRequest(
        domain=domain,
        email=str(email),
        method=str(request.params.get("method", "auto")),
        webroot=str(request.params.get("webroot", DEFAULT_WEBROOT)),
        staging=bool(request.params.get("staging", False)),
        certbot_binary=config.certbot_binary,
        timeout=config.timeout,
    )

    try:
        argv, result = await obtain_certificate(certbot_request, dry_run=options.dry_run)
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(argv)}",
            dry_run=True,
        )

    assert result is not None
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message=f"certificate obtained for {domain}" if result.ok else "certbot obtain failed",
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _renew_certificate(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: SslExecutorConfig,
) -> ActionResult:
    cert_name = str(request.params.get("cert_name") or request.target_id or "")
    if not cert_name:
        return _fail(request, "cert_name or target_id is required", options)

    if not is_command_available(config.certbot_binary) and not options.dry_run:
        return _fail(request, f"{config.certbot_binary} is not installed", options)

    try:
        argv, result = await renew_certificate(
            cert_name,
            certbot_binary=config.certbot_binary,
            timeout=config.timeout,
            staging=bool(request.params.get("staging", False)),
            dry_run=options.dry_run,
        )
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(argv)}",
            dry_run=True,
        )

    assert result is not None
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message=f"certificate renewed for {cert_name}" if result.ok else "certbot renew failed",
        stdout=result.stdout,
        stderr=result.stderr,
    )


_HANDLERS = {
    "view_certificate": _view_certificate,
    "renew_certificate": _renew_certificate,
    "obtain_certificate": _obtain_certificate,
}
