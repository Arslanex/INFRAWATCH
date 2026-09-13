from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    CYAN,
    DIM,
    GREEN,
    _c,
    _reset,
    emit_models,
    format_cron_schedule_hint,
    format_exit_code,
    print_empty,
    print_info_card,
    print_insight,
    print_report,
    print_section,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.cron.collector import collect_cron_jobs
from iw_agent.modules.cron.schemas import CronJob, CronJobExecution
from iw_agent.modules.cron.state_manager import (
    DEFAULT_EXECUTION_HISTORY_TAIL,
    collect_cron_executions,
)


async def run_cron(args: argparse.Namespace) -> None:
    jobs = await collect_cron_jobs()
    emit_models(jobs, json_output=args.json, plain=args.plain, render=_render_cron)


async def run_cron_history(args: argparse.Namespace) -> None:
    executions = await collect_cron_executions(
        log_directory=args.log_directory,
        tail=args.tail,
    )
    emit_models(executions, json_output=args.json, plain=args.plain, render=_render_cron_history)


def _cron_summary(jobs: list[CronJob]) -> str:
    owners = {job.owner for job in jobs}
    return f"Found {len(jobs)} scheduled job(s) for {len(owners)} user account(s)."


def _cron_history_summary(executions: list[CronJobExecution]) -> str:
    failed = sum(1 for execution in executions if execution.exit_code != 0)
    ok = len(executions) - failed
    return f"Showing {len(executions)} recent run(s): {ok} succeeded, {failed} failed."


def _render_cron_job_card(job: CronJob) -> None:
    schedule_hint = format_cron_schedule_hint(job.cron_expression)
    badge = f"{_c(GREEN)}● SCHEDULED{_reset()}"

    lines = [
        f"{_c(CYAN)}⏰{_reset()} {job.cron_expression}  {_c(DIM)}({schedule_hint}){_reset()}",
        f"{_c(DIM)}runs as:{_reset()} {job.owner}",
        job.command if len(job.command) <= 72 else f"{job.command[:69]}...",
    ]
    if job.output_log_path:
        lines.append(f"{_c(DIM)}log:{_reset()} {job.output_log_path}")

    print_info_card(
        badge=badge,
        title=job.command.split()[0] if job.command else job.owner,
        lines=lines,
        tone="ok",
    )


def _render_cron(jobs: list[CronJob]) -> None:
    print_report(
        "Scheduled tasks (cron)",
        "Automatic jobs that run on a timetable.",
    )
    if not jobs:
        print_empty(
            "no scheduled jobs",
            "No crontab entries were found for this server.",
            "this is normal if you do not use cron.",
        )
        return

    print_insight(_cron_summary(jobs))
    print_section(1, "Scheduled jobs", "Each card is one automatic task on this server.")
    for job in jobs:
        _render_cron_job_card(job)


def _render_history_card(execution: CronJobExecution) -> None:
    ok = execution.exit_code == 0
    badge = format_exit_code(execution.exit_code)
    tone = "ok" if ok else "bad"

    lines = [
        f"{_c(DIM)}when:{_reset()} {execution.started_at.strftime('%Y-%m-%d %H:%M UTC')}",
        f"{_c(DIM)}log:{_reset()} {execution.job_log_path}",
    ]

    print_info_card(
        badge=badge,
        title=execution.job_log_path.rsplit("/", 1)[-1],
        lines=lines,
        tone=tone,
    )


def _render_cron_history(executions: list[CronJobExecution]) -> None:
    print_report(
        "Cron job history",
        "Recent results of scheduled jobs.",
    )
    if not executions:
        print_empty(
            "no run history",
            "No .runs log files were found.",
            "history appears after InfraWatch-managed jobs run.",
        )
        return

    print_insight(_cron_history_summary(executions))
    print_section(1, "Recent runs", "Exit code 0 means the job finished successfully.")
    for execution in executions:
        _render_history_card(execution)


def _configure_history(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-dir",
        dest="log_directory",
        default="logs/cron",
        help="directory with .runs files (default: logs/cron)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=DEFAULT_EXECUTION_HISTORY_TAIL,
        help=f"lines per file (default: {DEFAULT_EXECUTION_HISTORY_TAIL})",
    )


COMMAND_SPECS = [
    CliCommandSpec("cron", "scheduled cron jobs", run_cron),
    CliCommandSpec("cron-history", "recent cron run results", run_cron_history, _configure_history),
]
