"""Project action menu."""
from iw_agent.modules.project.action_picker import hub_actions
from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary


def _project(**kwargs) -> ProjectSummary:
    defaults = dict(
        name="myapp",
        kind=ProjectKind.DOCKER_COMPOSE,
        source_type="git",
        repo_path="/tmp/myapp",
    )
    defaults.update(kwargs)
    return ProjectSummary(**defaults)


def test_compose_project_offers_deploy_and_stop():
    labels = [action.label for action in hub_actions(_project())]
    assert "Deploy stack" in labels
    assert "Stop stack" in labels
    assert "Re-detect stack" in labels
    assert labels[-1] == "Re-detect stack"


def test_static_project_has_publish_site():
    labels = [action.label for action in hub_actions(_project(kind=ProjectKind.STATIC))]
    assert "Publish site" in labels
    assert "Stop stack" not in labels
