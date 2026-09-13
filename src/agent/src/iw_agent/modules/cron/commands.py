from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_exit_code,
    format_optional,
    print_column_guide,
    print_data_table,
    print_empty,
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

CRON_COLUMNS = [
    ("User", "account that runs the job"),
    ("Schedule", "when the job runs (cron format)"),
    ("Command", "what the job executes"),
]

HISTORY_COLUMNS = [
    ("When", "start time of the run"),
    ("Result", "whether the job succeeded"),
    ("Log file", "where output is stored"),
]


async def run_cron(args: argparse.Namespace) -> None:
    jobs = await collect_cron_jobs()
    emit_models(jobs, json_output=args.json, plain=args.plain, render=_render_cron)


async def run_cron_history(args: argparse.Namespace) -> None:
    executions = await collect_cron_executions(
        log_directory=args.log_directory,
        tail=args.tail,
    )
    emit_models(executions, json_output=args.json, plain=args.plain, render=_render_cron_history)


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

    print_insight(f"Found {len(jobs)} scheduled job(s).")

    print_section(1, "Job list", "Review what runs automatically and when.")
    print_data_table(
        CRON_COLUMNS,
        [
            [
                job.owner,
                job.cron_expression,
                job.command[:70],
            ]
            for job in jobs
        ],
    )
    print_column_guide(CRON_COLUMNS)


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

    print_insight(f"Showing {len(executions)} recent run record(s).")

    print_section(1, "Recent runs", "Exit code 0 means the job finished successfully.")
    print_data_table(
        HISTORY_COLUMNS,
        [
            [
                execution.started_at.strftime("%Y-%m-%d %H:%M UTC"),
                format_exit_code(execution.exit_code),
                execution.job_log_path,
            ]
            for execution in executions
        ],
    )
    print_column_guide(HISTORY_COLUMNS)


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
