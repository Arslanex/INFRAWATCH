from __future__ import annotations

import os
import signal

import psutil

from iw_agent.core._thread import read
from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.modules.processes.collector import find_process
from iw_agent.modules.processes.schemas import Process

MODULE = "processes"
PROTECTED_PIDS = {1, os.getpid()}

PROCESS_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="view_details",
        label="View process details",
        kind=ActionKind.READ,
        description="Show CPU, memory, cgroup, and command line",
    ),
    ActionSpec(
        id="kill_process",
        label="Kill process",
        kind=ActionKind.DESTRUCTIVE,
        requires_root=True,
        description="Send SIGTERM to the process (use signal=KILL for SIGKILL)",
    ),
)

PROCESS_ACTIONS_BY_ID = {action.id: action for action in PROCESS_ACTIONS}


class ProcessExecutor:
    module = MODULE

    def actions(self) -> tuple[ActionSpec, ...]:
        return PROCESS_ACTIONS

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        if request.action_id not in PROCESS_ACTIONS_BY_ID:
            return _fail(request, f"unknown process action: {request.action_id}", options)

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


def _resolve_pid(request: ActionRequest) -> int | None:
    if request.target_id:
        try:
            return int(request.target_id)
        except ValueError:
            return None
    raw_pid = request.params.get("pid")
    if raw_pid is None:
        return None
    try:
        return int(raw_pid)
    except (TypeError, ValueError):
        return None


def _format_process_details(process: Process) -> str:
    lines = [
        f"pid={process.pid}",
        f"name={process.process_name}",
        f"owner={process.owner or '-'}",
        f"status={process.status or '-'}",
        f"cpu={process.cpu_percent if process.cpu_percent is not None else '-'}%",
    ]
    if process.memory_rss_bytes is not None:
        memory_mb = process.memory_rss_bytes / (1024 * 1024)
        lines.append(f"memory={memory_mb:.1f}MB")
    if process.parent_pid is not None:
        lines.append(f"ppid={process.parent_pid}")
    if process.process_group_id is not None:
        lines.append(f"pgid={process.process_group_id}")
    if process.cgroup_type:
        lines.append(f"cgroup_type={process.cgroup_type}")
    if process.container_id:
        lines.append(f"container_id={process.container_id}")
    if process.systemd_unit:
        lines.append(f"systemd_unit={process.systemd_unit}")
    if process.cgroup_owner:
        lines.append(f"cgroup_owner={process.cgroup_owner}")
    if process.started_at:
        lines.append(f"started={process.started_at.isoformat()}")
    if process.command_line:
        lines.append(f"command={process.command_line}")
    return "\n".join(lines)


async def _resolve_process(request: ActionRequest) -> Process | None:
    pid = _resolve_pid(request)
    if pid is None:
        return None
    return await find_process(pid)


def _signal_from_params(params: dict) -> signal.Signals:
    name = str(params.get("signal", "TERM")).upper()
    if name == "KILL":
        return signal.SIGKILL
    return signal.SIGTERM


def _kill_process_sync(pid: int, sig: signal.Signals) -> None:
    os.kill(pid, sig)


async def _view_details(
    request: ActionRequest,
    options: ExecutorOptions,
) -> ActionResult:
    process = await _resolve_process(request)
    if process is None:
        return _fail(request, "pid is required", options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=_format_process_details(process),
    )


async def _kill_process(
    request: ActionRequest,
    options: ExecutorOptions,
) -> ActionResult:
    pid = _resolve_pid(request)
    if pid is None:
        return _fail(request, "pid is required", options)
    if pid in PROTECTED_PIDS:
        return _fail(request, f"refusing to kill protected pid {pid}", options)

    process = await find_process(pid)
    if process is None:
        return _fail(request, f"process {pid} not found", options)

    sig = _signal_from_params(request.params)
    sig_name = "SIGKILL" if sig == signal.SIGKILL else "SIGTERM"

    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would send {sig_name} to pid {pid} ({process.process_name})",
            dry_run=True,
        )

    try:
        await read(_kill_process_sync, pid, sig)
    except ProcessLookupError:
        return _fail(request, f"process {pid} already exited", options)
    except PermissionError:
        return _fail(request, f"permission denied sending {sig_name} to pid {pid}", options)
    except OSError as exc:
        return _fail(request, f"failed to kill pid {pid}: {exc}", options)

    if sig == signal.SIGTERM:
        try:
            psutil.Process(pid).wait(timeout=2)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass

    still_running = await find_process(pid) is not None
    if still_running and sig == signal.SIGTERM:
        message = f"sent {sig_name} to pid {pid}; process may still be running"
    elif still_running:
        message = f"sent {sig_name} to pid {pid}; process still running"
    else:
        message = f"process {pid} ({process.process_name}) terminated"

    return ActionResult(
        ok=not still_running or sig == signal.SIGKILL,
        module=MODULE,
        action_id=request.action_id,
        message=message,
    )


_HANDLERS = {
    "view_details": _view_details,
    "kill_process": _kill_process,
}
