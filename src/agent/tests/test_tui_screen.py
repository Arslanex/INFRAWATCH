"""The screen repaints by difference; over SSH that is the difference between
a usable editor and a flickering one."""
import pytest

from iw_agent.cli.output import configure_output, truncate_visible, visible_length
from iw_agent.cli.tui.screen import Screen


@pytest.fixture(autouse=True)
def plain_mode():
    configure_output(plain=True)
    yield
    configure_output(plain=False)


@pytest.fixture
def screen():
    written = []
    return Screen(written.append, width=20, height=4), written


def test_first_flush_paints_everything(screen):
    view, written = screen
    view.set_row(0, "one")
    view.flush()

    assert len(written) == 1
    assert "one" in written[0]


def test_second_flush_paints_only_what_changed(screen):
    view, written = screen
    view.set_row(0, "one")
    view.set_row(1, "two")
    view.flush()
    written.clear()

    view.set_row(1, "three")
    view.flush()

    assert len(written) == 1
    assert "three" in written[0]
    assert "one" not in written[0]


def test_an_unchanged_frame_writes_nothing(screen):
    view, written = screen
    view.set_row(0, "steady")
    view.flush()
    written.clear()

    view.flush()

    assert written == []


def test_invalidate_forces_a_full_repaint(screen):
    view, written = screen
    view.set_row(0, "steady")
    view.flush()
    written.clear()

    view.invalidate()
    view.flush()

    assert written != []


def test_resize_clears_and_repaints(screen):
    view, written = screen
    view.set_row(0, "before")
    view.flush()
    written.clear()

    view.resize(40, 6)
    assert view.width == 40
    assert view.snapshot() == [""] * 6


def test_rows_are_truncated_to_the_width(screen):
    view, _ = screen
    view.set_row(0, "x" * 50)

    assert visible_length(view.row(0)) <= 20


def test_writing_past_the_last_row_is_ignored(screen):
    view, _ = screen
    view.set_row(99, "nowhere")

    assert view.snapshot() == ["", "", "", ""]


def test_snapshot_is_plain_rows(screen):
    view, _ = screen
    view.set_rows(0, ["a", "b"])

    assert view.snapshot() == ["a", "b", "", ""]


def test_truncate_keeps_colour_codes_balanced():
    configure_output(plain=False)
    out = truncate_visible("\033[32mhello world\033[0m", 8)

    assert visible_length(out) <= 8
    assert out.endswith("\033[0m")
