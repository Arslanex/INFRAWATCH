from __future__ import annotations

import os

from iw_agent.core.action_service import get_action_service
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.modules.nginx.collector import DEFAULT_SITES_AVAILABLE_DIR, collect_virtual_hosts
from iw_agent.modules.nginx.schemas import SiteKind, VirtualHost

_NGINX_PARAM_KEYS = (
    "nginx_binary",
    "timeout",
    "sites_available_dir",
    "sites_enabled_dir",
    "certbot_binary",
    "certbot_timeout",
    "certbot_live_dir",
    "webroot",
)


def build_server_names(
    domain: str,
    *,
    include_www: bool,
    extra_domains: list[str] | None = None,
) -> list[str]:
    names = [domain]
    if include_www:
        www = f"www.{domain}"
        if www not in names:
            names.append(www)
    for extra in extra_domains or []:
        if extra and extra not in names:
            names.append(extra)
    return names


async def find_virtual_host_for_domain(
    domain: str,
    *,
    nginx_binary: str,
    timeout: float,
) -> VirtualHost | None:
    hosts = await collect_virtual_hosts(nginx_binary=nginx_binary, timeout=timeout)
    for host in hosts:
        if domain in host.server_names:
            return host
    for host in hosts:
        if host.config_path.endswith(f"/{domain}"):
            return host
    return None


def nginx_params_from_request(params: dict) -> dict:
    return {key: params[key] for key in _NGINX_PARAM_KEYS if key in params}


def expected_config_path(domain: str, nginx_params: dict) -> str:
    sites_dir = str(nginx_params.get("sites_available_dir", DEFAULT_SITES_AVAILABLE_DIR))
    return os.path.join(sites_dir, domain)


def _sub_options(options: ExecutorOptions) -> ExecutorOptions:
    return ExecutorOptions(
        dry_run=options.dry_run,
        skip_confirm=True,
        audit_log_path=options.audit_log_path,
    )


def _nginx_runtime(nginx_params: dict) -> tuple[str, float]:
    return (
        str(nginx_params.get("nginx_binary", "nginx")),
        float(nginx_params.get("timeout", 30.0)),
    )


async def _resolve_host_for_domain(
    domain: str,
    nginx_params: dict,
    *,
    server_names: list[str],
    options: ExecutorOptions,
) -> VirtualHost | None:
    nginx_binary, timeout = _nginx_runtime(nginx_params)
    host = await find_virtual_host_for_domain(domain, nginx_binary=nginx_binary, timeout=timeout)
    if host is not None:
        return host
    if options.dry_run:
        return VirtualHost(
            config_path=expected_config_path(domain, nginx_params),
            server_names=server_names,
        )
    return None


async def ensure_proxy_site(
    *,
    domain: str,
    backend_port: int,
    server_names: list[str],
    nginx_params: dict,
    options: ExecutorOptions,
) -> tuple[ActionResult, str | None]:
    service = get_action_service()
    sub = _sub_options(options)
    base = nginx_params_from_request(nginx_params)
    proxy_pass = f"http://127.0.0.1:{backend_port}"
    nginx_binary, timeout = _nginx_runtime(base)

    if not options.dry_run:
        live = await find_virtual_host_for_domain(domain, nginx_binary=nginx_binary, timeout=timeout)
        if live is not None:
            result = await service.run(
                ActionRequest(
                    module="nginx",
                    action_id="apply_backend_settings",
                    target_id=live.config_path,
                    params={**base, "domain": domain, "proxy_pass": proxy_pass, "reload": True},
                ),
                options=sub,
            )
            return result, live.config_path

    result = await service.run(
        ActionRequest(
            module="nginx",
            action_id="create_site",
            target_id=domain,
            params={
                **base,
                "domain": domain,
                "site_kind": SiteKind.PROXY.value,
                "proxy_pass": proxy_pass,
                "server_names": server_names,
                "enable_site": True,
                "reload": True,
            },
        ),
        options=sub,
    )
    if not result.ok:
        return result, None

    config_path = expected_config_path(domain, base)
    if not options.dry_run:
        live = await find_virtual_host_for_domain(domain, nginx_binary=nginx_binary, timeout=timeout)
        if live is not None:
            config_path = live.config_path
    return result, config_path


async def ensure_static_site(
    *,
    domain: str,
    document_root: str,
    server_names: list[str],
    nginx_params: dict,
    options: ExecutorOptions,
) -> tuple[ActionResult, str | None]:
    service = get_action_service()
    sub = _sub_options(options)
    base = nginx_params_from_request(nginx_params)
    nginx_binary, timeout = _nginx_runtime(base)

    if not options.dry_run:
        live = await find_virtual_host_for_domain(domain, nginx_binary=nginx_binary, timeout=timeout)
        if live is not None:
            result = await service.run(
                ActionRequest(
                    module="nginx",
                    action_id="apply_backend_settings",
                    target_id=live.config_path,
                    params={
                        **base,
                        "domain": domain,
                        "document_root": document_root,
                        "reload": True,
                    },
                ),
                options=sub,
            )
            return result, live.config_path

    result = await service.run(
        ActionRequest(
            module="nginx",
            action_id="create_site",
            target_id=domain,
            params={
                **base,
                "domain": domain,
                "site_kind": SiteKind.STATIC.value,
                "document_root": document_root,
                "server_names": server_names,
                "enable_site": True,
                "reload": True,
            },
        ),
        options=sub,
    )
    if not result.ok:
        return result, None

    config_path = expected_config_path(domain, base)
    if not options.dry_run:
        live = await find_virtual_host_for_domain(domain, nginx_binary=nginx_binary, timeout=timeout)
        if live is not None:
            config_path = live.config_path
    return result, config_path


async def ensure_https(
    *,
    domain: str,
    email: str,
    server_names: list[str],
    nginx_params: dict,
    options: ExecutorOptions,
    staging: bool = False,
    force: bool = False,
) -> ActionResult:
    service = get_action_service()
    sub = _sub_options(options)
    base = nginx_params_from_request(nginx_params)

    host = await _resolve_host_for_domain(domain, base, server_names=server_names, options=options)
    if host is None:
        return ActionResult(
            ok=False,
            module="project",
            action_id="deploy_project",
            message=f"nginx site for {domain} not found — create the site before enabling HTTPS",
            dry_run=options.dry_run,
        )

    return await service.run(
        ActionRequest(
            module="nginx",
            action_id="secure_site",
            target_id=host.config_path,
            params={
                **base,
                "domain": domain,
                "email": email,
                "staging": staging,
                "force": force,
                "virtual_host": host.model_dump(mode="json"),
            },
        ),
        options=sub,
    )
