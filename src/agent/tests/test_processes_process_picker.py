"""Process picker navigation and card layout."""
import asyncio

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.card_picker import CardItem, CardPickerSession
from iw_agent.modules.processes.process_picker import pick_process, process_cards
from iw_agent.modules.processes.schemas import Process


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


def _process() -> Process:
    return Process(
        pid=1234,
        process_name="nginx",
        owner="www-data",
        status="running",
        cpu_percent=12.5,
        memory_rss_bytes=50_000_000,
        command_line="/usr/sbin/nginx -g daemon off;",
    )


def test_process_card_shows_cpu_and_pid():
    cards = process_cards([_process()])
    frame = "\n".join(cards[0].lines)
    assert "nginx" in frame
    assert "pid 1234" in frame
    assert "CPU:" in frame


class FakeTerminal:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def write(self, text):
        pass

    def size(self):
        return 100, 24

    def read(self, timeout=None):
        return self.chunks.pop(0) if self.chunks else b""

    def wait_for_escape_tail(self):
        return b""


def test_pick_process_selects_with_enter():
    process = _process()
    terminal = FakeTerminal([b"\r"])

    result = asyncio.run(
        pick_process([process], summary="1 process", terminal=terminal),
    )

    assert result.value == process
    assert not result.quit_session


def test_card_picker_session_quit_on_q():
    session = CardPickerSession(
        title="Test",
        subtitle="processes",
        items=[CardItem(lines=["line"], value=_process())],
    )
    session.handle("q")
    assert session.quit_session
