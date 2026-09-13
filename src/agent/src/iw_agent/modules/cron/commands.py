from __future__ import annotations

import argparse
from collections import defaultdict

from iw_agent.cli.output import (
    emit_models,
    format_cron_schedule_hint,
    format_exit_code,
    format_field,
    format_fields,
    print_empty,
    print_group_heading,
    print_info_box,
    print_insight,
    print_report,
    print_status_box,
    status_badge,
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
    lines = [
        format_field("Why", "runs automatically on this server's clock"),
        format_field("Schedule", job.cron_expression),
        format_field("When", schedule_hint),
        format_field("Runs as", job.owner),
        format_field(
            "Command",
            job.command if len(job.command) <= 72 else f"{job.command[:69]}...",
        ),
    ]
    if job.output_log_path:
        lines.append(format_field("Log", job.output_log_path))

    print_status_box(
        badge=status_badge("SCHEDULED", "ok"),
        title=_job_title(job),
        lines=lines,
        tone="ok",
    )


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

    print_info_box(
        title="How to read",
        hint="field guide",
        lines=format_fields(
            [
                ("Schedule", "cron expression (minute hour day month weekday)"),
                ("When", "plain-English summary of the schedule"),
                ("Runs as", "user account that executes the command"),
                ("Command", "shell command that runs on schedule"),
                ("Log", "InfraWatch run log path, if configured"),
            ]
        ),
    )

    for owner, owner_jobs in _group_jobs_by_owner(jobs):
        print_group_heading(owner, f"{len(owner_jobs)} job(s)")
        for job in owner_jobs:
            _render_cron_job(job)


def _history_badge(execution: CronJobExecution) -> tuple[str, str]:
    if execution.exit_code == 0:
        return status_badge("OK (0)", "ok"), "ok"
    return status_badge(f"FAILED ({execution.exit_code})", "bad"), "bad"


def _render_history_entry(execution: CronJobExecution) -> None:
    badge, tone = _history_badge(execution)
    why = (
        "job finished without errors"
        if execution.exit_code == 0
        else "check the log file for error output"
    )
    lines = [
        format_field("Why", why),
        format_field("When", execution.started_at.strftime("%Y-%m-%d %H:%M UTC")),
        format_field("Log", execution.job_log_path),
    ]

    print_status_box(
        badge=badge,
        title=execution.job_log_path.rsplit("/", 1)[-1],
        lines=lines,
        tone=tone,
    )


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

    print_info_box(
        title="How to read",
        hint="field guide",
        lines=format_fields(
            [
                ("Result", f"{format_exit_code(0)} = success  |  failed (N) = error"),
                ("When", "UTC timestamp when the job started"),
                ("Log", "path to the .runs log file on this server"),
            ]
        ),
    )

    for panel_title, panel_hint, group in _group_executions(executions):
        if not group:
            continue
        print_group_heading(panel_title, panel_hint)
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
