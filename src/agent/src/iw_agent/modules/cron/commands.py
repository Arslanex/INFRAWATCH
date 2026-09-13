from __future__ import annotations

import argparse
from collections import defaultdict

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import pause, run_action_in_hub
from iw_agent.cli.interactive.context import PageContext
from iw_agent.cli.interactive.hub import pick_or_fallback, run_action_hub
from iw_agent.cli.interactive.selector import prompt_choice
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
    print_menu_item,
    print_page_divider,
    print_page_summary,
    print_report,
    print_status_box,
    prepare_command_view,
    status_badge,
)
from iw_agent.cli.parser import add_interactive_flags
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.core.paths import cron_log_dir
from iw_agent.modules.cron.collector import collect_cron_jobs
from iw_agent.modules.cron.schemas import CronJob, CronJobExecution
from iw_agent.modules.cron.state_manager import (
    DEFAULT_EXECUTION_HISTORY_TAIL,
    collect_cron_executions,
)


async def run_cron(args: argparse.Namespace) -> None:
    if getattr(args, "interactive", False):
        await run_cron_interactive(args)
        return

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
        format_field("Status", "enabled" if job.enabled else "disabled"),
        format_field(
            "Command",
            job.command if len(job.command) <= 72 else f"{job.command[:69]}...",
        ),
    ]
    if job.output_log_path:
        lines.append(format_field("Log", job.output_log_path))
    if not job.writable:
        lines.append(format_field("Note", f"{job.source} crontab — read-only here"))

    badge_label = "SCHEDULED" if job.enabled else "DISABLED"
    tone = "ok" if job.enabled else "warn"
    print_status_box(
        badge=status_badge(badge_label, tone),
        title=_job_title(job),
        lines=lines,
        tone=tone,
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


def _configure_cron(parser: argparse.ArgumentParser) -> None:
    add_interactive_flags(parser)
    parser.add_argument(
        "--log-dir",
        dest="log_directory",
        default=str(cron_log_dir()),
        help="directory with .runs files (default: logs/cron)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=DEFAULT_EXECUTION_HISTORY_TAIL,
        help=f"history lines per file (default: {DEFAULT_EXECUTION_HISTORY_TAIL})",
    )


def _configure_history(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-dir",
        dest="log_directory",
        default=str(cron_log_dir()),
        help="directory with .runs files (default: logs/cron)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=DEFAULT_EXECUTION_HISTORY_TAIL,
        help=f"lines per file (default: {DEFAULT_EXECUTION_HISTORY_TAIL})",
    )


def _job_params(context: PageContext, job: CronJob) -> dict:
    return {
        "job_id": job.job_id,
        "log_directory": context.args.log_directory,
        "tail": context.args.tail,
    }


def _last_run_hint(
    job: CronJob,
    executions: list[CronJobExecution],
) -> str:
    if not job.output_log_path:
        return ""
    matching = [
        execution
        for execution in executions
        if execution.job_log_path == job.output_log_path
    ]
    if not matching:
        return ""
    latest = max(matching, key=lambda item: item.started_at)
    return "OK" if latest.exit_code == 0 else "failed"


def _job_list_hint(job: CronJob, executions: list[CronJobExecution]) -> str:
    schedule = format_cron_schedule_hint(job.cron_expression)
    state = "on" if job.enabled else "off"
    last = _last_run_hint(job, executions)
    parts = [schedule, f"as {job.owner}", state]
    if last:
        parts.append(f"last: {last}")
    if not job.writable:
        parts.append("system")
    return " · ".join(parts)


async def _refresh_cron_context(context: PageContext) -> None:
    context.data["jobs"] = await collect_cron_jobs()
    context.data["executions"] = await collect_cron_executions(
        context.args.log_directory,
        tail=context.args.tail,
    )


async def _run_job_action(
    context: PageContext,
    job: CronJob,
    action_id: str,
) -> ActionResult | None:
    request = ActionRequest(
        module="cron",
        action_id=action_id,
        target_id=job.job_id,
        params=_job_params(context, job),
    )
    return await run_action_in_hub(
        request,
        options=context.data["options"],
        target_label=_job_title(job),
    )


async def _interactive_pick_job(
    args: argparse.Namespace,
    jobs: list[CronJob],
    executions: list[CronJobExecution],
):
    from iw_agent.modules.cron.job_picker import pick_job

    summary = _cron_summary(jobs) if jobs else "No scheduled jobs on this server."
    return await pick_or_fallback(
        lambda: pick_job(
            jobs,
            executions,
            summary=summary,
            dry_run=getattr(args, "dry_run", False),
        ),
        lambda: _interactive_pick_job_fallback(jobs, executions),
    )


async def _interactive_pick_job_fallback(
    jobs: list[CronJob],
    executions: list[CronJobExecution],
) -> CronJob | None:
    from iw_agent.cli.output import clear_screen, print_page_header

    clear_screen()
    print_page_header("Scheduled tasks", "cron")
    print_page_divider()
    print_page_summary(_cron_summary(jobs))
    for index, job in enumerate(jobs, start=1):
        print_menu_item(index, _job_title(job), _job_list_hint(job, executions))
    choice = prompt_choice(max_value=len(jobs), allow_back=False, allow_exit=True)
    if choice is None:
        return None
    return jobs[choice - 1]


async def _interactive_job_hub(context: PageContext, job: CronJob) -> bool:
    from iw_agent.modules.cron.action_picker import pick_job_action

    return await run_action_hub(
        job,
        pick=lambda target: pick_job_action(
            target,
            job_title=_job_title(target),
            dry_run=context.data["options"].dry_run,
        ),
        perform=lambda target, action: _perform_hub_action(context, target, action),
    )


async def _perform_hub_action(
    context: PageContext,
    job: CronJob,
    action,
) -> CronJob:
    if action.kind == "local" or not action.action_id:
        print(f"\n{job.command}")
        pause()
        return job

    result = await _run_job_action(context, job, action.action_id)
    if result is None:
        pause()
        return job

    print()
    if action.action_id == "view_details":
        print(result.message)
    else:
        print_action_result(result)
    pause()

    if result.ok and action.action_id in {"enable_job", "disable_job"}:
        await _refresh_cron_context(context)
        return next(
            (item for item in context.data["jobs"] if item.job_id == job.job_id),
            job,
        )
    return job


async def run_cron_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"jobs": [], "executions": [], "options": options},
    )
    await _refresh_cron_context(context)

    if not context.data["jobs"]:
        print_page_divider()
        print_page_summary("No scheduled jobs found on this server.")
        pause()
        return

    while True:
        await _refresh_cron_context(context)
        jobs = context.data["jobs"]
        executions = context.data["executions"]
        picked = await _interactive_pick_job(args, jobs, executions)
        if picked.quit_session:
            break
        if picked.value is None:
            continue
        if await _interactive_job_hub(context, picked.value):
            break


COMMAND_SPECS = [
    CliCommandSpec("cron", "scheduled cron jobs", run_cron, _configure_cron),
    CliCommandSpec("cron-history", "recent cron run results", run_cron_history, _configure_history),
]
