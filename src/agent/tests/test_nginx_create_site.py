"""Interactive new-site flow must not double-confirm after the wizard."""
import argparse
from unittest.mock import AsyncMock

import pytest

from iw_agent.cli.interactive.navigator import PageContext
from iw_agent.core.actions import ActionResult, ExecutorOptions
from iw_agent.modules.nginx import commands


@pytest.mark.asyncio
async def test_create_site_action_skips_second_confirm_when_requested(monkeypatch):
    captured: dict = {}

    async def fake_run_action_with_prompts(request, *, options, target_label=""):
        captured["skip_confirm"] = options.skip_confirm
        captured["action_id"] = request.action_id
        return ActionResult(
            ok=True,
            module="nginx",
            action_id="create_site",
            message="created /etc/nginx/sites-available/demo.test",
        )

    monkeypatch.setattr(commands, "run_action_with_prompts", fake_run_action_with_prompts)
    monkeypatch.setattr(commands, "_refresh_profiles", AsyncMock())
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    context = PageContext(
        args=argparse.Namespace(
            nginx_binary="nginx",
            timeout=10,
            certbot_live_dir="/etc/letsencrypt/live",
        ),
        data={"profiles": [], "options": ExecutorOptions()},
    )
    ok = await commands._run_create_site_action(
        context,
        {"domain": "demo.test", "site_kind": "static"},
        pause=False,
        skip_confirm=True,
    )

    assert ok is True
    assert captured["skip_confirm"] is True
    assert captured["action_id"] == "create_site"


@pytest.mark.asyncio
async def test_interactive_create_site_retries_invalid_domain(monkeypatch):
    monkeypatch.setattr(commands, "has_effective_root", lambda: True)
    monkeypatch.setattr(commands, "clear_screen", lambda: None)
    inputs = iter(["not a domain", "q"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(inputs))

    host = await commands._interactive_create_site(
        argparse.Namespace(nginx_binary="nginx", timeout=10),
        [],
        ExecutorOptions(dry_run=True),
    )

    assert host is None


@pytest.mark.asyncio
async def test_interactive_create_site_requires_root_before_wizard(monkeypatch):
    monkeypatch.setattr(commands, "has_effective_root", lambda: False)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    host = await commands._interactive_create_site(
        argparse.Namespace(nginx_binary="nginx", timeout=10),
        [],
        ExecutorOptions(dry_run=False),
    )

    assert host is None
