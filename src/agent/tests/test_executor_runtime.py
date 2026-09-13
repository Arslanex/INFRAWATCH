import pytest

from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.exceptions import ActionDeniedError
from iw_agent.core.executor_runtime import run_action


async def _noop_handler(request, options):
    return ActionResult(
        ok=True,
        module="test",
        action_id=request.action_id,
        message="ok",
        dry_run=options.dry_run,
    )


@pytest.mark.asyncio
async def test_dry_run_skips_root_check(monkeypatch):
    spec = ActionSpec(
        id="needs_root",
        label="Needs root",
        kind=ActionKind.WRITE,
        requires_root=True,
    )
    monkeypatch.setattr("iw_agent.core.executor_runtime.has_effective_root", lambda: False)

    result = await run_action(
        spec,
        ActionRequest(module="test", action_id="needs_root"),
        _noop_handler,
        options=ExecutorOptions(dry_run=True, skip_confirm=True),
    )

    assert result.ok is True


@pytest.mark.asyncio
async def test_write_still_requires_root_without_dry_run(monkeypatch):
    spec = ActionSpec(
        id="needs_root",
        label="Needs root",
        kind=ActionKind.WRITE,
        requires_root=True,
    )
    monkeypatch.setattr("iw_agent.core.executor_runtime.has_effective_root", lambda: False)

    with pytest.raises(ActionDeniedError, match="requires root"):
        await run_action(
            spec,
            ActionRequest(module="test", action_id="needs_root"),
            _noop_handler,
            options=ExecutorOptions(dry_run=False, skip_confirm=True),
        )
