from __future__ import annotations

from pathlib import Path

from crontab import CronTab

from iw_agent.core._thread import read
from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.commands import is_command_available, run_command
from iw_agent.modules.cron.collector import find_cron_job
from iw_agent.modules.cron.schemas import CronJob, compute_job_id
from iw_agent.modules.cron.state_manager import (
    DEFAULT_EXECUTION_HISTORY_TAIL,
    collect_cron_executions,
)

MODULE = "cron"
DEFAULT_RUN_TIMEOUT = 300.0

CRON_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="view_details",
        label="View job details",
        kind=ActionKind.READ,
        description="Show schedule, command, and log path for one cron job",
    ),
    ActionSpec(
        id="view_job_history",
        label="View run history",
        kind=ActionKind.READ,
        description="Show recent .runs entries for this job's log path",
    ),
    ActionSpec(
        id="tail_job_log",
        label="Tail output log",
        kind=ActionKind.READ,
        description="Show the last lines of the job's stdout/stderr redirect log",
    ),
    ActionSpec(
        id="enable_job",
        label="Enable job",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Uncomment a user crontab entry",
    ),
    ActionSpec(
        id="disable_job",
        label="Disable job",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Comment out a user crontab entry",
    ),
    ActionSpec(
        id="run_job_now",
        label="Run job now",
        kind=ActionKind.WRITE,
        requires_root=True,
        description="Execute the job command once as its owner",
    ),
)

CRON_ACTIONS_BY_ID = {action.id: action for action in CRON_ACTIONS}


class CronExecutor:
    module = MODULE

    def actions(self) -> tuple[ActionSpec, ...]:
        return CRON_ACTIONS

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        if request.action_id not in CRON_ACTIONS_BY_ID:
            return _fail(request, f"unknown cron action: {request.action_id}", options)

        handler = _HANDLERS.get(request.action_id)
        if handler is None:
            return _fail(request, f"handler missing for {request.action_id}", options)
        return await handler(request, options)


def _fail(request: ActionRequest, message: str, options: ExecutorOptions) -> ActionResult:
    return ActionResult(
        ok=False,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


async def _resolve_job(request: ActionRequest) -> CronJob | None:
    job_id = request.target_id or str(request.params.get("job_id") or "")
    if not job_id:
        return None
    return await find_cron_job(job_id)


def _format_job_details(job: CronJob) -> str:
    schedule = job.cron_expression
    lines = [
        f"owner={job.owner}",
        f"schedule={schedule}",
        f"enabled={'yes' if job.enabled else 'no'}",
        f"writable={'yes' if job.writable else 'no'}",
        f"source={job.source}",
        f"command={job.command}",
    ]
    if job.output_log_path:
        lines.append(f"log={job.output_log_path}")
    return "\n".join(lines)


async def _view_details(request: ActionRequest, options: ExecutorOptions) -> ActionResult:
    job = await _resolve_job(request)
    if job is None:
        return _fail(request, "job_id is required", options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=_format_job_details(job),
    )


async def _view_job_history(request: ActionRequest, options: ExecutorOptions) -> ActionResult:
    job = await _resolve_job(request)
    if job is None:
        return _fail(request, "job_id is required", options)
    if not job.output_log_path:
        return _fail(request, "this job has no InfraWatch log redirect configured", options)

    log_directory = str(request.params.get("log_directory", "logs/cron"))
    tail = int(request.params.get("tail", DEFAULT_EXECUTION_HISTORY_TAIL))
    executions = await collect_cron_executions(log_directory, tail=tail)
    matching = [
        execution
        for execution in executions
        if execution.job_log_path == job.output_log_path
    ]
    if not matching:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"no run history for {job.output_log_path}",
        )

    matching.sort(key=lambda item: item.started_at, reverse=True)
    lines = [
        (
            f"{execution.started_at.strftime('%Y-%m-%d %H:%M UTC')} "
            f"exit={execution.exit_code}"
        )
        for execution in matching[:tail]
    ]
    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message="\n".join(lines),
    )


async def _tail_job_log(request: ActionRequest, options: ExecutorOptions) -> ActionResult:
    job = await _resolve_job(request)
    if job is None:
        return _fail(request, "job_id is required", options)
    if not job.output_log_path:
        return _fail(request, "this job has no output log redirect", options)

    tail = int(request.params.get("tail", 50))
    log_path = Path(job.output_log_path)
    if not log_path.is_file():
        return _fail(request, f"log file not found: {job.output_log_path}", options)

    try:
        lines = log_path.read_text(errors="replace").splitlines()[-tail:]
    except OSError as exc:
        return _fail(request, f"cannot read log: {exc}", options)

    if not lines:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"{job.output_log_path} is empty",
        )

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message="\n".join(lines),
    )


def _find_user_crontab_entry(job: CronJob):
    crontab = CronTab(user=job.owner)
    for entry in crontab:
        if not entry.is_valid():
            continue
        command = str(entry.command or "").strip()
        if not command:
            continue
        owner = str(entry.user or job.owner)
        cron_expression = str(entry.slices)
        if compute_job_id(owner, cron_expression, command) == job.job_id:
            return crontab, entry
    return None, None


def _set_job_enabled(job: CronJob, enabled: bool, *, dry_run: bool) -> str:
    if not job.writable:
        raise RuntimeError(f"system cron jobs are read-only ({job.source})")
    if job.enabled == enabled:
        state = "enabled" if enabled else "disabled"
        return f"job is already {state}"

    crontab, entry = _find_user_crontab_entry(job)
    if crontab is None or entry is None:
        raise RuntimeError(f"crontab entry not found for job {job.job_id}")

    if dry_run:
        action = "enable" if enabled else "disable"
        return f"dry-run: would {action} job for {job.owner}"

    entry.enable(enabled)
    crontab.write()
    action = "enabled" if enabled else "disabled"
    return f"job {action} for {job.owner}"


async def _enable_job(request: ActionRequest, options: ExecutorOptions) -> ActionResult:
    job = await _resolve_job(request)
    if job is None:
        return _fail(request, "job_id is required", options)

    try:
        message = await read(_set_job_enabled, job, True, dry_run=options.dry_run)
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


async def _disable_job(request: ActionRequest, options: ExecutorOptions) -> ActionResult:
    job = await _resolve_job(request)
    if job is None:
        return _fail(request, "job_id is required", options)

    try:
        message = await read(_set_job_enabled, job, False, dry_run=options.dry_run)
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


async def _run_as_user(
    owner: str,
    command: str,
    timeout: float,
) -> tuple[list[str], object]:
    if is_command_available("runuser"):
        argv = ["runuser", "-u", owner, "--", "sh", "-c", command]
    elif is_command_available("su"):
        argv = ["su", "-", owner, "-c", command]
    else:
        raise RuntimeError("neither runuser nor su is available")

    result = await run_command(argv, timeout=timeout)
    return argv, result


async def _run_job_now(request: ActionRequest, options: ExecutorOptions) -> ActionResult:
    job = await _resolve_job(request)
    if job is None:
        return _fail(request, "job_id is required", options)

    timeout = float(request.params.get("timeout", DEFAULT_RUN_TIMEOUT))
    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run as {job.owner}: {job.command}",
            dry_run=True,
        )

    try:
        argv, result = await _run_as_user(job.owner, job.command, timeout)
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    message = (
        f"job finished with exit code {result.exit_code}"
        if result.ok
        else f"job failed with exit code {result.exit_code}"
    )
    if result.timed_out:
        message = f"job timed out after {timeout:.0f}s"

    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        stdout=result.stdout,
        stderr=result.stderr,
    )


_HANDLERS = {
    "view_details": _view_details,
    "view_job_history": _view_job_history,
    "tail_job_log": _tail_job_log,
    "enable_job": _enable_job,
    "disable_job": _disable_job,
    "run_job_now": _run_job_now,
}
