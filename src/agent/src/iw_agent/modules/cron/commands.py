from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import Navigator, Page, PageContext, PageResult
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
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError
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
        default="logs/cron",
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
        default="logs/cron",
        help="directory with .runs files (default: logs/cron)",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=DEFAULT_EXECUTION_HISTORY_TAIL,
        help=f"lines per file (default: {DEFAULT_EXECUTION_HISTORY_TAIL})",
    )


@dataclass(frozen=True)
class _HubEntry:
    label: str
    hint: str = ""
    action_id: str = ""
    kind: str = "action"


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


def _job_hub_menu(job: CronJob) -> list[_HubEntry]:
    menu: list[_HubEntry] = [
        _HubEntry("Run now", "execute once as job owner", "run_job_now"),
    ]
    if job.writable:
        if job.enabled:
            menu.append(_HubEntry("Disable", "comment out crontab line", "disable_job"))
        else:
            menu.append(_HubEntry("Enable", "uncomment crontab line", "enable_job"))
    if job.output_log_path:
        menu.append(
            _HubEntry("View history", ".runs execution log", "view_job_history"),
        )
    menu.append(_HubEntry("More", "details, output log"))
    return menu


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
    try:
        return await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=_job_title(job),
        )
    except ActionCancelledError:
        print("\nCancelled.")
        return None
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        return None


async def run_cron_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    jobs = await collect_cron_jobs()
    executions = await collect_cron_executions(args.log_directory, tail=args.tail)
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"jobs": jobs, "executions": executions, "options": options},
    )
    await Navigator(context).run(_InteractiveJobListPage())


class _InteractiveJobListPage(Page):
    @property
    def title(self) -> str:
        return "Cron jobs"

    @property
    def subtitle(self) -> str:
        return "cron"

    def render(self, context: PageContext) -> None:
        jobs: list[CronJob] = context.data["jobs"]
        executions: list[CronJobExecution] = context.data["executions"]
        print_page_divider()
        if not jobs:
            print_page_summary("No scheduled jobs found on this server.")
            return

        for index, job in enumerate(jobs, start=1):
            print_menu_item(index, _job_title(job), _job_list_hint(job, executions))

    async def handle(self, context: PageContext) -> PageResult | Page:
        jobs: list[CronJob] = context.data["jobs"]
        if not jobs:
            return PageResult.EXIT

        choice = prompt_choice(max_value=len(jobs), allow_back=False, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        return _InteractiveJobDetailPage(jobs[choice - 1])


class _InteractiveJobDetailPage(Page):
    def __init__(self, job: CronJob) -> None:
        self._job = job
        self._menu = _job_hub_menu(job)

    @property
    def title(self) -> str:
        return _job_title(self._job)

    @property
    def subtitle(self) -> str:
        return "cron"

    def render(self, context: PageContext) -> None:
        executions: list[CronJobExecution] = context.data["executions"]
        print_page_divider()
        print_page_summary(_job_list_hint(self._job, executions))
        print_page_divider()
        for index, entry in enumerate(self._menu, start=1):
            print_menu_item(index, entry.label, entry.hint)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._menu), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        entry = self._menu[choice - 1]
        if entry.kind == "more" or not entry.action_id:
            return _JobMorePage(self._job)

        result = await _run_job_action(context, self._job, entry.action_id)
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        print_action_result(result)
        input("\nPress Enter to continue...")
        if result.ok and entry.action_id in {"enable_job", "disable_job"}:
            await _refresh_cron_context(context)
            refreshed = next(
                (job for job in context.data["jobs"] if job.job_id == self._job.job_id),
                self._job,
            )
            self._job = refreshed
            self._menu = _job_hub_menu(refreshed)
        return PageResult.STAY


class _JobMorePage(Page):
    def __init__(self, job: CronJob) -> None:
        self._job = job

    @property
    def title(self) -> str:
        return _job_title(self._job)

    @property
    def subtitle(self) -> str:
        return "cron · more"

    def render(self, context: PageContext) -> None:
        job = self._job
        print_page_divider()
        print_page_summary(format_cron_schedule_hint(job.cron_expression))
        print(f"\n   Runs as: {job.owner}")
        print(f"   Source: {job.source} ({'writable' if job.writable else 'read-only'})")
        print(f"   Command:\n   {job.command}")
        if job.output_log_path:
            print(f"\n   Log: {job.output_log_path}")
        print_page_divider()
        print_menu_item(1, "View details")
        if job.output_log_path:
            print_menu_item(2, "Tail output log")
        print_menu_item(3 if job.output_log_path else 2, "View full command")

    async def handle(self, context: PageContext) -> PageResult | Page:
        max_value = 3 if self._job.output_log_path else 2
        choice = prompt_choice(max_value=max_value, allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        if choice == 1:
            action_id = "view_details"
        elif choice == 2 and self._job.output_log_path:
            action_id = "tail_job_log"
        else:
            print(f"\n{self._job.command}")
            input("\nPress Enter to continue...")
            return PageResult.STAY

        result = await _run_job_action(context, self._job, action_id)
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        if action_id == "view_details":
            print(result.message)
        else:
            print_action_result(result)
        input("\nPress Enter to continue...")
        return PageResult.STAY


COMMAND_SPECS = [
    CliCommandSpec("cron", "scheduled cron jobs", run_cron, _configure_cron),
    CliCommandSpec("cron-history", "recent cron run results", run_cron_history, _configure_history),
]
