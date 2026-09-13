from __future__ import annotations

from iw_agent.core.actions import ActionHandler, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.executor_runtime import (
    has_effective_root,
    requires_confirmation,
    run_action,
    write_audit_log,
)

__all__ = [
    "has_effective_root",
    "requires_confirmation",
    "run_action",
    "write_audit_log",
]


async def execute_action(
    spec: ActionSpec,
    request: ActionRequest,
    handler: ActionHandler,
    *,
    options: ExecutorOptions | None = None,
    target_label: str = "",
) -> ActionResult:
    """Low-level runner — prefer ActionService for module dispatch."""
    return await run_action(
        spec,
        request,
        handler,
        options=options,
        target_label=target_label,
    )
