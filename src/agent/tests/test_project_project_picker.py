"""Project picker navigation and card layout."""
import asyncio

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.card_picker import CardPickerSession
from iw_agent.modules.project.project_picker import ProjectListChoice, pick_project, project_list_cards
from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


def _project() -> ProjectSummary:
    return ProjectSummary(
        name="myapp",
        kind=ProjectKind.DOCKER_COMPOSE,
        source_type="git",
        repo_path="/tmp/myapp",
        deploy_ok=True,
        containers_running=2,
    )


def test_project_card_shows_type_and_status():
    cards = project_list_cards([_project()])
    frame = "\n".join(cards[0].lines)
    assert "myapp" in frame
    assert "Type:" in frame
    assert "docker-compose" in frame


def test_project_list_includes_add_option():
    cards = project_list_cards([_project()])
    assert cards[-1].value.kind == "add"


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


def test_pick_project_selects_with_enter():
    project = _project()
    terminal = FakeTerminal([b"\r"])
    result = asyncio.run(
        pick_project(
            [project],
            summary="1 project",
            terminal=terminal,
        ),
    )

    assert result.value == ProjectListChoice(kind="project", project=project)
    assert not result.quit_session


def test_card_picker_session_quit_on_q():
    session = CardPickerSession(
        title="Test",
        subtitle="project",
        items=project_list_cards([_project()]),
    )
    session.handle("q")
    assert session.quit_session
