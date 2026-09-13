from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from iw_agent.core.actions import (
    ActionHandler,
    ActionKind,
    ActionRequest,
    ActionResult,
    ActionSpec,
    ExecutorOptions,
)
from iw_agent.core.exceptions import ActionDeniedError
from iw_agent.core.logger import logger


async def run_action(
    spec: ActionSpec,
    request: ActionRequest,
    handler: ActionHandler,
    *,
    options: ExecutorOptions | None = None,
    target_label: str = "",
) -> ActionResult:
    opts = options or ExecutorOptions()
    if spec.requires_root and not opts.dry_run and not has_effective_root():
        raise ActionDeniedError(
            f"{spec.label} requires root — rerun with sudo",
        )

    try:
        result = await handler(request, opts)
    except Exception as exc:
        logger.exception("action failed: %s", spec.id)
        result = ActionResult(
            ok=False,
            module=request.module,
            action_id=request.action_id,
            message=str(exc),
            dry_run=opts.dry_run,
        )
    else:
        if result.module != request.module:
            result = result.model_copy(update={"module": request.module})

    write_audit_log(
        spec=spec,
        request=request,
        result=result,
        options=opts,
        target_label=target_label,
    )
    return result


def write_audit_log(
    *,
    spec: ActionSpec,
    request: ActionRequest,
    result: ActionResult,
    options: ExecutorOptions,
    target_label: str = "",
) -> None:
    log_path = Path(options.audit_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "module": request.module,
        "action_id": spec.id,
        "kind": spec.kind.value,
        "target_id": request.target_id,
        "target_label": target_label,
        "dry_run": options.dry_run or result.dry_run,
        "ok": result.ok,
        "message": result.message,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def has_effective_root() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def requires_confirmation(spec: ActionSpec) -> bool:
    return spec.kind != ActionKind.READ
