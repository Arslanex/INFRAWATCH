"""Bridge from the editor to the action pipeline.

The editor draws its own confirmation, so it passes ``skip_confirm`` and never
reaches the ``input()`` calls in :mod:`iw_agent.cli.action_prompts` — which
would fight raw mode.
"""
from __future__ import annotations

from iw_agent.core.action_service import get_action_service
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions


async def save_config(
    *,
    config_path: str,
    content: str,
    expected_sha256: str,
    params: dict,
    dry_run: bool = False,
    audit_log_path: str | None = None,
) -> ActionResult:
    options = ExecutorOptions(dry_run=dry_run, skip_confirm=True)
    if audit_log_path:
        options.audit_log_path = audit_log_path

    request = ActionRequest(
        module="nginx",
        action_id="write_site_config",
        target_id=config_path,
        params={
            **params,
            "content": content,
            "expected_sha256": expected_sha256,
            "reload": False,
        },
    )
    return await get_action_service().run(request, options=options)


async def reload_nginx(*, config_path: str, params: dict,
                       audit_log_path: str | None = None) -> ActionResult:
    options = ExecutorOptions(skip_confirm=True)
    if audit_log_path:
        options.audit_log_path = audit_log_path
    request = ActionRequest(
        module="nginx",
        action_id="reload",
        target_id=config_path,
        params=dict(params),
    )
    return await get_action_service().run(request, options=options)


async def run_named_action(
    *,
    action_id: str,
    config_path: str,
    params: dict,
    dry_run: bool = False,
    audit_log_path: str | None = None,
) -> ActionResult:
    """Run one of the existing nginx actions on the site being edited."""
    options = ExecutorOptions(dry_run=dry_run, skip_confirm=True)
    if audit_log_path:
        options.audit_log_path = audit_log_path
    request = ActionRequest(
        module="nginx",
        action_id=action_id,
        target_id=config_path,
        params=dict(params),
    )
    return await get_action_service().run(request, options=options)
