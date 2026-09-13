"""Docker container action menu."""
from iw_agent.modules.docker.action_picker import hub_actions
from iw_agent.modules.docker.schemas import Container


def _container(**kwargs) -> Container:
    defaults = dict(
        container_id="abc",
        container_name="web",
        image_name="nginx:latest",
        state="running",
    )
    defaults.update(kwargs)
    return Container(**defaults)


def test_running_container_offers_restart_and_stop():
    labels = [action.label for action in hub_actions(_container())]
    assert "Restart" in labels
    assert "Stop" in labels
    assert "Start" not in labels
    assert "Logs" in labels


def test_stopped_container_offers_start():
    labels = [action.label for action in hub_actions(_container(state="exited"))]
    assert "Start" in labels
    assert "Restart" not in labels
    assert "Stop" not in labels
