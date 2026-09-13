"""The shared pick-then-act loop every interactive command runs."""
import pytest

from iw_agent.cli.interactive.hub import HubAction, pick_or_fallback, run_action_hub
from iw_agent.cli.tui.card_picker import CardPickerUnavailable, PickResult

RESTART = HubAction("Restart", "stop then start", "restart")


@pytest.mark.asyncio
async def test_pick_or_fallback_returns_the_picker_result():
    async def pick():
        return PickResult(value="picked")

    async def fallback():  # pragma: no cover - must not run
        raise AssertionError("fallback should not be used")

    result = await pick_or_fallback(pick, fallback)

    assert result.value == "picked"


@pytest.mark.asyncio
async def test_pick_or_fallback_uses_the_menu_when_the_tui_cannot_draw():
    async def pick():
        raise CardPickerUnavailable("no tty")

    async def fallback():
        return "from menu"

    result = await pick_or_fallback(pick, fallback)

    assert result.value == "from menu"
    assert result.quit_session is False


@pytest.mark.asyncio
async def test_pick_or_fallback_treats_an_empty_menu_choice_as_quit():
    async def pick():
        raise CardPickerUnavailable("no tty")

    async def fallback():
        return None

    result = await pick_or_fallback(pick, fallback)

    assert result.value is None
    assert result.quit_session is True


@pytest.mark.asyncio
async def test_hub_quits_the_whole_session():
    async def pick(_target):
        return PickResult(quit_session=True)

    async def perform(_target, _action):  # pragma: no cover - must not run
        raise AssertionError("no action should run")

    assert await run_action_hub("target", pick=pick, perform=perform) is True


@pytest.mark.asyncio
async def test_hub_backs_out_to_the_list():
    async def pick(_target):
        return PickResult(value=None)

    async def perform(_target, _action):  # pragma: no cover - must not run
        raise AssertionError("no action should run")

    assert await run_action_hub("target", pick=pick, perform=perform) is False


@pytest.mark.asyncio
async def test_hub_keeps_managing_the_refreshed_target():
    seen = []

    async def pick(target):
        seen.append(target)
        if len(seen) == 3:
            return PickResult(value=None)
        return PickResult(value=RESTART)

    async def perform(target, action):
        assert action is RESTART
        return f"{target}+"

    assert await run_action_hub("t", pick=pick, perform=perform) is False
    assert seen == ["t", "t+", "t++"]


@pytest.mark.asyncio
async def test_hub_drops_to_the_list_when_the_target_is_gone():
    calls = []

    async def pick(target):
        calls.append(target)
        return PickResult(value=RESTART)

    async def perform(_target, _action):
        return None

    assert await run_action_hub("t", pick=pick, perform=perform) is False
    assert calls == ["t"]
