"""Site picker navigation and card layout."""
import asyncio
import pathlib

import pytest

from iw_agent.cli.output import configure_output
from iw_agent.cli.tui.keys import Key
from iw_agent.cli.tui.screen import Screen
from iw_agent.modules.nginx.schemas import SiteProfile, SslStatus, VirtualHost
from iw_agent.modules.nginx.site_picker import SitePickerSession, pick_site

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "nginx"


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


def _profile(name: str, *, enabled: bool = True) -> SiteProfile:
    host = VirtualHost(
        config_path=f"/etc/nginx/sites-available/{name}",
        server_names=[name],
        listen_ports=[80],
        upstream="http://127.0.0.1:3000",
        ssl_enabled=False,
        enabled=enabled,
    )
    return SiteProfile(virtual_host=host, ssl_status=SslStatus.NO_SSL)


def test_new_site_is_first_and_selected_by_default():
    session = SitePickerSession.from_profiles([_profile("a.test")], summary="1 site")
    assert session.cards[0].kind == "new"
    assert session.cursor == 0


def test_down_moves_to_first_site():
    session = SitePickerSession.from_profiles([_profile("a.test")], summary="1 site")
    session.handle(Key.DOWN)
    assert session.cursor == 1
    assert session.cards[1].kind == "site"


def test_enter_on_new_site_returns_marker():
    session = SitePickerSession.from_profiles([], summary="empty")
    session.handle(Key.ENTER)
    assert session.result == "__new__"
    assert session.running is False


def test_q_quits():
    session = SitePickerSession.from_profiles([_profile("a.test")], summary="1 site")
    session.handle("q")
    assert session.result is None


def test_enter_on_site_returns_host():
    profile = _profile("demo.test")
    session = SitePickerSession.from_profiles([profile], summary="1 site")
    session.handle(Key.DOWN)
    session.handle(Key.ENTER)
    assert session.result == profile.virtual_host


def test_frame_shows_status_box_fields():
    session = SitePickerSession.from_profiles([_profile("demo.test")], summary="1 site(s)")
    session.handle(Key.DOWN)
    frame = "\n".join(session.frame_lines(100, 24))
    assert "demo.test" in frame
    assert "Forwards" in frame
    assert "Config" in frame


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


def test_pick_site_loop_accepts_arrow_and_enter():
    profiles = [_profile("demo.test")]
    terminal = FakeTerminal([b"\x1b[B", b"\r"])  # down, enter

    result = asyncio.run(
        pick_site(profiles, summary="1 site", terminal=terminal),
    )

    assert result == profiles[0].virtual_host
