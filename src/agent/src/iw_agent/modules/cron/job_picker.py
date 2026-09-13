"""Full-screen cron job picker for ``iw cron -i``."""
from __future__ import annotations

from iw_agent.cli.output import format_cron_schedule_hint, format_field
from iw_agent.cli.tui.card_picker import LIST_FOOTER, CardItem, PickResult, pick_card
from iw_agent.cli.tui.cards import card_lines
from iw_agent.modules.cron.schemas import CronJob, CronJobExecution


def _job_title(job: CronJob) -> str:
    if not job.command:
        return job.owner
    token = job.command.split()[0]
    return token.rsplit("/", 1)[-1] or job.owner


def _last_run_label(job: CronJob, executions: list[CronJobExecution]) -> str:
    if not job.output_log_path:
        return "no log configured"
    matching = [
        execution
        for execution in executions
        if execution.job_log_path == job.output_log_path
    ]
    if not matching:
        return "no runs logged yet"
    latest = max(matching, key=lambda item: item.started_at)
    when = latest.started_at.strftime("%Y-%m-%d %H:%M UTC")
    result = "OK" if latest.exit_code == 0 else f"failed ({latest.exit_code})"
    return f"{when} · {result}"


def _job_card(job: CronJob, executions: list[CronJobExecution]) -> CardItem[CronJob]:
    status = "enabled" if job.enabled else "disabled"
    if not job.writable:
        status = f"{status} · read-only ({job.source})"
    body = [
        format_field("Why", "runs automatically on this server's clock"),
        format_field(
            "Schedule",
            f"{job.cron_expression} — {format_cron_schedule_hint(job.cron_expression)}",
        ),
        format_field("Runs as", job.owner),
        format_field("Status", status),
        format_field("Last run", _last_run_label(job, executions)),
    ]
    return CardItem(
        lines=card_lines(_job_title(job), body, strike_title=not job.enabled),
        value=job,
    )


def job_cards(
    jobs: list[CronJob],
    executions: list[CronJobExecution],
) -> list[CardItem[CronJob]]:
    return [_job_card(job, executions) for job in jobs]


async def pick_job(
    jobs: list[CronJob],
    executions: list[CronJobExecution],
    *,
    summary: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[CronJob]:
    return await pick_card(
        job_cards(jobs, executions),
        title="Scheduled tasks",
        subtitle="cron",
        summary=summary,
        footer=LIST_FOOTER,
        dry_run=dry_run,
        terminal=terminal,
    )
