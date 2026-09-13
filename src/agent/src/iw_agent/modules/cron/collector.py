from __future__ import annotations

import pwd
from pathlib import Path

from crontab import CronTab

from iw_agent.core._thread import read
from iw_agent.core.exceptions import CronCrontabUnreadableError
from iw_agent.core.logger import logger
from iw_agent.modules.cron.schemas import CronJob, compute_job_id

SYSTEM_CRONTAB_FILES = ("/etc/crontab",)
SYSTEM_CRONTAB_DROPINS_DIR = "/etc/cron.d"


async def collect_cron_jobs() -> list[CronJob]:
    return await read(_collect_cron_jobs)


def _collect_cron_jobs() -> list[CronJob]:
    jobs: list[CronJob] = []

    # 1. Kullanıcı crontab'larını oku
    jobs.extend(_collect_user_crontab_jobs())

    # 2. Sistem crontab dosyalarını oku
    jobs.extend(_collect_system_crontab_jobs())

    logger.debug("collected %d cron jobs", len(jobs))
    return jobs


def _collect_user_crontab_jobs() -> list[CronJob]:
    jobs: list[CronJob] = []

    for username in _login_usernames():
        try:
            crontab = CronTab(user=username)
        except (OSError, ValueError) as exc:
            logger.debug(
                "%s",
                CronCrontabUnreadableError(f"user={username}: {exc}"),
            )
            continue

        jobs.extend(
            _jobs_from_crontab(
                crontab,
                default_owner=username,
                source="user",
                writable=True,
            )
        )

    return jobs


def _collect_system_crontab_jobs() -> list[CronJob]:
    jobs: list[CronJob] = []
    crontab_paths = [Path(path) for path in SYSTEM_CRONTAB_FILES]
    dropins_dir = Path(SYSTEM_CRONTAB_DROPINS_DIR)

    if dropins_dir.is_dir():
        try:
            crontab_paths.extend(
                sorted(entry for entry in dropins_dir.iterdir() if entry.is_file())
            )
        except OSError as exc:
            logger.debug(
                "%s",
                CronCrontabUnreadableError(
                    f"{SYSTEM_CRONTAB_DROPINS_DIR}: {exc}"
                ),
            )

    for crontab_path in crontab_paths:
        if not crontab_path.is_file():
            continue

        try:
            crontab = CronTab(tabfile=str(crontab_path), user=False)
        except (OSError, ValueError) as exc:
            logger.debug(
                "%s",
                CronCrontabUnreadableError(f"{crontab_path}: {exc}"),
            )
            continue

        jobs.extend(
            _jobs_from_crontab(
                crontab,
                default_owner="root",
                source="system",
                writable=False,
            )
        )

    return jobs


def _jobs_from_crontab(
    crontab: CronTab,
    default_owner: str,
    *,
    source: str,
    writable: bool,
) -> list[CronJob]:
    jobs: list[CronJob] = []

    for entry in crontab:
        if not entry.is_valid():
            continue

        command = str(entry.command or "").strip()
        if not command:
            continue

        owner = str(entry.user or default_owner)
        cron_expression = str(entry.slices)
        jobs.append(
            CronJob(
                job_id=compute_job_id(owner, cron_expression, command),
                owner=owner,
                cron_expression=cron_expression,
                command=command,
                enabled=entry.is_enabled(),
                writable=writable,
                source=source,  # type: ignore[arg-type]
                output_log_path=_extract_output_log_path(command),
            )
        )

    return jobs


async def find_cron_job(job_id: str) -> CronJob | None:
    jobs = await collect_cron_jobs()
    return next((job for job in jobs if job.job_id == job_id), None)


def _extract_output_log_path(command: str) -> str | None:
    for redirect in (">>", ">"):
        _, separator, tail = command.partition(redirect)
        if separator and tail.strip():
            candidate = tail.strip().split()[0]
            if candidate.startswith("/"):
                return candidate
    return None


def _login_usernames() -> list[str]:
    usernames: dict[str, None] = {}

    for passwd_entry in pwd.getpwall():
        if passwd_entry.pw_uid != 0 and passwd_entry.pw_uid < 1000:
            continue
        if passwd_entry.pw_shell.endswith(("nologin", "false")):
            continue
        usernames[passwd_entry.pw_name] = None

    return list(usernames)


if __name__ == "__main__":
    import asyncio

    async def _main() -> None:
        jobs = await collect_cron_jobs()
        print(f"found {len(jobs)} cron jobs\n")
        for job in jobs:
            print(
                f"{job.owner:<12} {job.cron_expression:<20} "
                f"log={job.output_log_path or '-':<30} "
                f"{job.command[:60]}"
            )

    asyncio.run(_main())
