from __future__ import annotations

from iw_agent.cli.action_prompts import confirm_action
from iw_agent.core.action_service import ActionService, get_action_service
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.core.exceptions import ActionCancelledError
from iw_agent.core.executor_runtime import requires_confirmation


async def run_action_with_prompts(
    request: ActionRequest,
    *,
    options: ExecutorOptions | None = None,
    target_label: str = "",
    service: ActionService | None = None,
) -> ActionResult:
    action_service = service or get_action_service()
    spec = action_service.get_spec(request.module, request.action_id)
    opts = options or ExecutorOptions()

    if not opts.skip_confirm and requires_confirmation(spec):
        confirm_action(spec, target_label=target_label, dry_run=opts.dry_run)

    try:
        return await action_service.run(
            request,
            options=opts,
            target_label=target_label,
        )
    except ActionCancelledError:
        raise
