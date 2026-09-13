from __future__ import annotations

import argparse
from collections import defaultdict

from iw_agent.cli.output import (
    BOLD,
    DIM,
    GREEN,
    RED,
    _c,
    _reset,
    emit_models,
    format_cron_schedule_hint,
    format_exit_code,
    print_empty,
    print_field_rows,
    print_insight,
    print_panel,
    print_report,
)
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.modules.cron.collector import collect_cron_jobs
from iw_agent.modules.cron.schemas import CronJob, CronJobExecution
from iw_agent.modules.cron.state_manager import (
    DEFAULT_EXECUTION_HISTORY_TAIL,
    collect_cron_executions,
)

_FIELD_WIDTH = 11


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
    return f"{len(jobs)} scheduled job(s) across {len(owners)} user account(s)."


def _cron_history_summary(executions: list[CronJobExecution]) -> str:
    failed = sum(1 for execution in executions if execution.exit_code != 0)
    ok = len(executions) - failed
    return f"{len(executions)} recent run(s): {ok} succeeded, {failed} failed."


def _job_title(job: CronJob) -> str:
    if not job.command:
        return job.owner
    token = job.command.split()[0]
    return token.rsplit("/", 1)[-1] or job.owner


def _render_cron_job(job: CronJob) -> None:
    schedule_hint = format_cron_schedule_hint(job.cron_expression)
    title = _job_title(job)

    print(f"   {_c(BOLD)}{title}{_reset()}")
    print(f"   {'-' * 48}")

    rows: list[tuple[str, str]] = [
        ("Status", f"{_c(GREEN)}SCHEDULED{_reset()}"),
        ("Why", "runs automatically on this server's clock"),
        ("Schedule", job.cron_expression),
        ("When", f"{schedule_hint}  {_c(DIM)}(plain-English hint){_reset()}"),
        ("Runs as", job.owner),
        ("Command", job.command if len(job.command) <= 72 else f"{job.command[:69]}..."),
    ]
    if job.output_log_path:
        rows.append(("Log", job.output_log_path))

    print_field_rows(rows, label_width=_FIELD_WIDTH)
    print()


def _group_jobs_by_owner(jobs: list[CronJob]) -> list[tuple[str, list[CronJob]]]:
    grouped: dict[str, list[CronJob]] = defaultdict(list)
    for job in jobs:
        grouped[job.owner].append(job)

    return [
        (owner, sorted(group, key=lambda item: (item.cron_expression, item.command)))
        for owner, group in sorted(grouped.items())
    ]


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

    print_panel("How to read", hint="field guide")
    print_field_rows(
        [
            ("Schedule", "cron expression (minute hour day month weekday)"),
            ("When", "plain-English summary of the schedule"),
            ("Runs as", "user account that executes the command"),
            ("Command", "shell command that runs on schedule"),
            ("Log", "InfraWatch run log path, if configured"),
        ],
        label_width=_FIELD_WIDTH,
    )
    print()

    for owner, owner_jobs in _group_jobs_by_owner(jobs):
        print_panel(owner, hint=f"{len(owner_jobs)} job(s)")
        for job in owner_jobs:
            _render_cron_job(job)


def _history_title(execution: CronJobExecution) -> str:
    return execution.job_log_path.rsplit("/", 1)[-1]


def _history_status_fields(execution: CronJobExecution) -> list[tuple[str, str]]:
    ok = execution.exit_code == 0
    if ok:
        return [
            ("Result", format_exit_code(execution.exit_code)),
            ("Why", "job finished without errors"),
        ]
    return [
        ("Result", format_exit_code(execution.exit_code)),
        ("Why", "check the log file for error output"),
    ]


def _render_history_entry(execution: CronJobExecution) -> None:
    print(f"   {_c(BOLD)}{_history_title(execution)}{_reset()}")
    print(f"   {'-' * 48}")

    rows = [
        *_history_status_fields(execution),
        ("When", execution.started_at.strftime("%Y-%m-%d %H:%M UTC")),
        ("Log", execution.job_log_path),
    ]
    print_field_rows(rows, label_width=_FIELD_WIDTH)
    print()


def _group_executions(
    executions: list[CronJobExecution],
) -> list[tuple[str, str, list[CronJobExecution]]]:
    failed = [execution for execution in executions if execution.exit_code != 0]
    ok = [execution for execution in executions if execution.exit_code == 0]
    return [
        ("Failed", "job did not finish cleanly", failed),
        ("Succeeded", "finished with exit code 0", ok),
    ]


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

    print_panel("How to read", hint="field guide")
    print_field_rows(
        [
            ("Result", f"{_c(GREEN)}OK (0){_reset()} = success  |  {_c(RED)}failed (N){_reset()} = error"),
            ("When", "UTC timestamp when the job started"),
            ("Log", "path to the .runs log file on this server"),
        ],
        label_width=_FIELD_WIDTH,
    )
    print()

    for panel_title, panel_hint, group in _group_executions(executions):
        if not group:
            continue
        print_panel(panel_title, hint=panel_hint)
        for execution in group:
            _render_history_entry(execution)


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
