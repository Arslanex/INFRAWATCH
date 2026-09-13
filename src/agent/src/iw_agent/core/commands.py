from __future__ import annotations

import asyncio
import os
import shutil
import signal
from dataclasses import dataclass

from iw_agent.core.logger import logger

_REAP_TIMEOUT = 5.0


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def is_command_available(binary: str) -> bool:
    return shutil.which(binary) is not None


async def run_command(
    argv: list[str],
    timeout: float,
    cwd: str | None = None,
) -> CommandResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        start_new_session=True,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        await _kill_process_group(process)
        logger.warning("command timed out after %.1fs: %s", timeout, argv[0])
        return CommandResult(
            tuple(argv),
            exit_code=-1,
            stdout="",
            stderr="",
            timed_out=True,
        )

    return CommandResult(
        argv=tuple(argv),
        exit_code=process.returncode if process.returncode is not None else -1,
        stdout=stdout.decode(errors="replace"),
        stderr=stderr.decode(errors="replace"),
    )


async def _kill_process_group(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        try:
            process.kill()
        except ProcessLookupError:
            return

    try:
        await asyncio.wait_for(process.wait(), timeout=_REAP_TIMEOUT)
    except asyncio.TimeoutError:
        logger.error("could not reap a killed command: %s", process.pid)
