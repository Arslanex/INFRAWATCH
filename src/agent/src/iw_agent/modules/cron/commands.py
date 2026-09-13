from __future__ import annotations

import argparse

from iw_agent.cli.output import (
    emit_models,
    format_optional,
    print_result_count,
    print_table,
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
    emit_models(jobs, json_output=args.json, render=_render_cron)


async def run_cron_history(args: argparse.Namespace) -> None:
    executions = await collect_cron_executions(
        log_directory=args.log_directory,
        tail=args.tail,
    )
    emit_models(executions, json_output=args.json, render=_render_cron_history)


def _render_cron(jobs: list[CronJob]) -> None:
    print_result_count("cron job", len(jobs))
    print_table(
        ["OWNER", "SCHEDULE", "LOG", "COMMAND"],
        [
            [
                job.owner,
                job.cron_expression,
                format_optional(job.output_log_path),
                job.command[:60],
            ]
            for job in jobs
        ],
        widths=[12, 18, 28, 40],
    )


def _render_cron_history(executions: list[CronJobExecution]) -> None:
    print_result_count("cron run", len(executions))
    print_table(
        ["STARTED", "EXIT", "LOG"],
        [
            [
                execution.started_at.isoformat(),
                str(execution.exit_code),
                execution.job_log_path,
            ]
            for execution in executions
        ],
        widths=[26, 6, 36],
    )


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
