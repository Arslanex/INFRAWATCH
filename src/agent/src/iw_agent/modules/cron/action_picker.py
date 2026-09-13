"""Action picker for a selected cron job."""
from __future__ import annotations

from iw_agent.cli.tui.card_picker import PickResult
from iw_agent.cli.interactive.hub import HubAction, pick_hub_action
from iw_agent.modules.cron.schemas import CronJob


def hub_actions(job: CronJob) -> list[HubAction]:
    actions = [
        HubAction("Run now", "execute once as job owner", "run_job_now"),
    ]
    if job.writable:
        if job.enabled:
            actions.append(HubAction("Disable", "comment out crontab line", "disable_job"))
        else:
            actions.append(HubAction("Enable", "uncomment crontab line", "enable_job"))
    if job.output_log_path:
        actions.append(HubAction("View history", ".runs execution log", "view_job_history"))
        actions.append(HubAction("Tail output log", "last lines from log file", "tail_job_log"))
    actions.append(HubAction("View details", "schedule, owner, source", "view_details"))
    actions.append(HubAction("Show command", "print the full shell command", kind="local"))
    return actions


async def pick_job_action(
    job: CronJob,
    *,
    job_title: str,
    dry_run: bool = False,
    terminal=None,
) -> PickResult[HubAction]:
    return await pick_hub_action(
        hub_actions(job),
        title=job_title,
        subtitle="cron · actions",
        dry_run=dry_run,
        terminal=terminal,
    )
