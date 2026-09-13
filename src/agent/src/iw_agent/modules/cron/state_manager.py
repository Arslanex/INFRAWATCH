from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from iw_agent.core._thread import read
from iw_agent.core.exceptions import CronExecutionLogUnreadableError
from iw_agent.core.logger import logger
from iw_agent.core.paths import cron_log_dir
from iw_agent.modules.cron.schemas import CronJobExecution

EXECUTION_HISTORY_SUFFIX = ".runs"
EXECUTION_HISTORY_LINE = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2}))\s+"
    r"exit=(?P<exit_code>-?\d+)\s*$"
)
DEFAULT_EXECUTION_HISTORY_TAIL = 50


async def collect_cron_executions(
    log_directory: str,
    tail: int = DEFAULT_EXECUTION_HISTORY_TAIL,
) -> list[CronJobExecution]:
    return await read(_collect_cron_executions, log_directory, tail)


def _collect_cron_executions(
    log_directory: str,
    tail: int,
) -> list[CronJobExecution]:
    directory = Path(log_directory)
    if not directory.is_dir():
        return []

    executions: list[CronJobExecution] = []

    # 1. .runs dosyalarını listele
    try:
        history_files = sorted(directory.glob(f"*{EXECUTION_HISTORY_SUFFIX}"))
    except OSError as exc:
        logger.debug(
            "%s",
            CronExecutionLogUnreadableError(f"cannot list {log_directory}: {exc}"),
        )
        return []

    # 2. Her dosyadan son çalışmaları oku
    for history_file in history_files:
        executions.extend(_read_execution_history(history_file, tail))

    logger.debug("collected %d cron executions", len(executions))
    return executions


def _read_execution_history(
    history_file: Path,
    tail: int,
) -> list[CronJobExecution]:
    job_log_path = str(history_file)[: -len(EXECUTION_HISTORY_SUFFIX)]

    try:
        lines = history_file.read_text(errors="replace").splitlines()[-tail:]
    except OSError as exc:
        logger.debug(
            "%s",
            CronExecutionLogUnreadableError(f"cannot read {history_file}: {exc}"),
        )
        return []

    executions: list[CronJobExecution] = []

    # 3. Satırları parse et
    for line in lines:
        match = EXECUTION_HISTORY_LINE.match(line.strip())
        if match is None:
            continue

        executions.append(
            CronJobExecution(
                job_log_path=job_log_path,
                started_at=datetime.fromisoformat(
                    match.group("timestamp").replace("Z", "+00:00")
                ),
                exit_code=int(match.group("exit_code")),
            )
        )

    return executions


if __name__ == "__main__":
    import asyncio
    import sys

    async def _main() -> None:
        log_directory = sys.argv[1] if len(sys.argv) > 1 else str(cron_log_dir())
        tail = (
            int(sys.argv[2])
            if len(sys.argv) > 2
            else DEFAULT_EXECUTION_HISTORY_TAIL
        )

        executions = await collect_cron_executions(log_directory, tail)
        print(
            f"found {len(executions)} cron executions in {log_directory}\n"
        )
        for execution in executions:
            print(
                f"{execution.started_at.isoformat()} "
                f"exit={execution.exit_code:<4} {execution.job_log_path}"
            )

    asyncio.run(_main())
