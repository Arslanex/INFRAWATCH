"""Process action menu."""
from iw_agent.modules.processes.action_picker import hub_actions
from iw_agent.modules.processes.schemas import Process


def test_process_hub_offers_details_and_kill():
    process = Process(pid=1, process_name="systemd")
    labels = [action.label for action in hub_actions(process)]
    assert "View details" in labels
    assert "Kill process" in labels
