"""SSL certificate picker navigation and card layout."""
import asyncio
from datetime import datetime, timezone

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.card_picker import CardPickerSession
from iw_agent.modules.ssl.cert_picker import CertListChoice, cert_list_cards, pick_certificate
from iw_agent.modules.ssl.schemas import Certificate


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


def _certificate(*, days_left: int = 60) -> Certificate:
    not_after = datetime.now(timezone.utc).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    from datetime import timedelta

    not_after = not_after + timedelta(days=days_left)
    return Certificate(
        domain="app.example.com",
        issuer="Let's Encrypt",
        not_after=not_after,
        cert_path="/etc/letsencrypt/live/app.example.com/fullchain.pem",
        source="certbot",
    )


def test_cert_card_shows_expiry_and_source():
    cards = cert_list_cards([_certificate()])
    cert_card = cards[0]
    frame = "\n".join(cert_card.lines)
    assert "app.example.com" in frame
    assert "Expires:" in frame
    assert "certbot" in frame


def test_cert_list_includes_obtain_option():
    cards = cert_list_cards([_certificate()])
    assert cards[-1].value.kind == "obtain"


def test_obtain_only_when_no_certificates():
    cards = cert_list_cards([])
    assert len(cards) == 1
    assert cards[0].value.kind == "obtain"


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


def test_pick_certificate_selects_with_enter():
    certificate = _certificate()
    terminal = FakeTerminal([b"\r"])

    result = asyncio.run(
        pick_certificate([certificate], summary="1 cert", terminal=terminal),
    )

    assert result.value == CertListChoice(kind="cert", certificate=certificate)
    assert not result.quit_session


def test_card_picker_session_quit_on_q():
    session = CardPickerSession(
        title="Test",
        subtitle="ssl",
        items=cert_list_cards([_certificate()]),
    )
    session.handle("q")
    assert session.quit_session
