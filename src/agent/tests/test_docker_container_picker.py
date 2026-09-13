"""Docker container picker navigation and card layout."""
import asyncio
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.card_picker import CardItem, CardPickerSession
from iw_agent.cli.tui.keys import Key
from iw_agent.modules.docker.container_picker import container_cards, pick_container
from iw_agent.modules.docker.schemas import Container, PublishedPort

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


def _container(*, state: str = "running") -> Container:
    return Container(
        container_id="abc123def456",
        container_name="web-app",
        image_name="nginx:latest",
        state=state,
        compose_project_name="myapp",
        compose_service_name="web",
        published_ports=[
            PublishedPort(host_ip="0.0.0.0", host_port=8080, container_port=80, protocol="tcp"),
        ],
    )


def test_container_card_shows_status_and_ports():
    cards = container_cards([_container()])
    frame = "\n".join(cards[0].lines)
    assert "web-app" in frame
    assert "Status:" in frame
    assert "Ports:" in frame
    assert "myapp" in frame


def test_stopped_container_card_strikes_title():
    configure_output(plain=False)
    cards = container_cards([_container(state="exited")])
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


def test_pick_container_selects_with_enter():
    container = _container()
    terminal = FakeTerminal([b"\r"])

    result = asyncio.run(
        pick_container([container], summary="1 container", terminal=terminal),
    )

    assert result.value == container
    assert not result.quit_session


def test_card_picker_session_quit_on_q():
    session = CardPickerSession(
        title="Test",
        subtitle="docker",
        items=[CardItem(lines=["line"], value=_container())],
    )
    session.handle("q")
    assert session.quit_session
    assert session.result is None
