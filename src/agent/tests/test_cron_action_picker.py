"""Cron job action menu."""
from iw_agent.modules.cron.action_picker import hub_actions
from iw_agent.modules.cron.schemas import CronJob


def _job(**kwargs) -> CronJob:
    defaults = dict(
        job_id="x",
        owner="user",
        cron_expression="* * * * *",
        command="/bin/true",
        enabled=True,
        writable=True,
        source="user",
        output_log_path="/tmp/job.runs",
    )
    defaults.update(kwargs)
    return CronJob(**defaults)


def test_writable_enabled_job_offers_disable():
    labels = [action.label for action in hub_actions(_job())]
    assert "Run now" in labels
    assert "Disable" in labels
    assert "Enable" not in labels


def test_read_only_job_has_no_enable_disable():
    labels = [action.label for action in hub_actions(_job(writable=False, source="system"))]
    assert "Enable" not in labels
    assert "Disable" not in labels
    assert "Run now" in labels
