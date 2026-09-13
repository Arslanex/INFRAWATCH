"""Project status and action labels."""
from iw_agent.modules.project.action_picker import hub_actions
from iw_agent.modules.project.display import (
    primary_action_label,
    project_status_label,
    publish_wizard_intro,
)
from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary


def _project(**kwargs) -> ProjectSummary:
    defaults = dict(
        name="myapp",
        kind=ProjectKind.PROXY,
        source_type="local",
        repo_path="/tmp/myapp",
    )
    defaults.update(kwargs)
    return ProjectSummary(**defaults)


def test_proxy_status_not_published():
    assert "not published" in project_status_label(_project())


def test_proxy_status_published():
    status = project_status_label(
        _project(deploy_ok=True, domain="app.example.com"),
    )
    assert "published" in status
    assert "app.example.com" in status


def test_compose_primary_action_is_deploy_stack():
    assert primary_action_label(ProjectKind.DOCKER_COMPOSE) == "Deploy stack"


def test_proxy_primary_action_is_publish_to_web():
    assert primary_action_label(ProjectKind.PROXY) == "Publish to web"


def test_proxy_wizard_mentions_uvicorn():
    intro = publish_wizard_intro(ProjectKind.PROXY)
    assert "uvicorn" in intro.lower()


def test_hub_puts_redetect_last():
    labels = [action.label for action in hub_actions(_project())]
    assert labels[0] == "Publish to web"
    assert labels[-1] == "Re-detect stack"
    assert "Detect" not in labels


def test_compose_hub_has_deploy_and_stop():
    project = _project(kind=ProjectKind.DOCKER_COMPOSE)
    labels = [action.label for action in hub_actions(project)]
    assert "Deploy stack" in labels
    assert "Stop stack" in labels
