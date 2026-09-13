"""SSL certificate action menu."""
from datetime import datetime, timezone

from iw_agent.modules.ssl.action_picker import hub_actions
from iw_agent.modules.ssl.schemas import Certificate


def _certificate(**kwargs) -> Certificate:
    defaults = dict(
        domain="app.example.com",
        not_after=datetime.now(timezone.utc),
        cert_path="/etc/letsencrypt/live/app.example.com/fullchain.pem",
        source="certbot",
    )
    defaults.update(kwargs)
    return Certificate(**defaults)


def test_certbot_cert_offers_renew_and_details():
    labels = [action.label for action in hub_actions(_certificate())]
    assert "Renew certificate" in labels
    assert "View details" in labels


def test_non_certbot_cert_has_no_renew():
    labels = [action.label for action in hub_actions(_certificate(source="nginx"))]
    assert "Renew certificate" not in labels
    assert "View details" in labels
