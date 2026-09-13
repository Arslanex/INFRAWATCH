"""Cron job picker navigation and card layout."""
import asyncio
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.card_picker import CardPickerSession, CardItem
from iw_agent.cli.tui.keys import Key
from iw_agent.modules.cron.job_picker import job_cards, pick_job
from iw_agent.modules.cron.schemas import CronJob, CronJobExecution
from datetime import datetime, timezone

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


def _job(*, enabled: bool = True, writable: bool = True) -> CronJob:
    return CronJob(
        job_id="abc123",
        owner="deploy",
        cron_expression="0 3 * * *",
        command="/usr/local/bin/backup.sh",
        enabled=enabled,
        writable=writable,
        source="user",
        output_log_path="/var/log/cron/backup.runs",
    )


def test_job_card_shows_schedule_and_status():
    cards = job_cards([_job()], [])
    frame = "\n".join(cards[0].lines)
    assert "backup" in frame.lower() or "backup.sh" in frame
    assert "Schedule:" in frame
    assert "Status:" in frame


def test_disabled_job_card_strikes_title():
    configure_output(plain=False)
    cards = job_cards([_job(enabled=False)], [])
    assert cards[0].lines[0]


class FakeTerminal:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.written = []

    def write(self, text):
        self.written.append(text)

    def size(self):
        return 100, 24

    def read(self, timeout=None):
        return self.chunks.pop(0) if self.chunks else b""

    def wait_for_escape_tail(self):
        return b""


def test_pick_job_selects_with_enter():
    job = _job()
    terminal = FakeTerminal([b"\r"])

    result = asyncio.run(
        pick_job([job], [], summary="1 job", terminal=terminal),
    )

    assert result.value == job
    assert not result.quit_session


def test_card_picker_session_quit_on_q():
    session = CardPickerSession(
        title="Test",
        subtitle="cron",
        items=[CardItem(lines=["line"], value=_job())],
    )
    session.handle("q")
    assert session.quit_session
    assert session.result is None
