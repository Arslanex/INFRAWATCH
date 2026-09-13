"""The nested config menus are gone and the editor is the single way in."""
import argparse
import asyncio
import inspect

import pytest

import iw_agent.modules.nginx.commands as commands
from iw_agent.cli.app import build_parser

REMOVED_PAGES = [
    "_InteractiveSiteDetailPage",
    "_SiteMorePage",
    "_ConfigEditorPage",
    "_TrafficHubPage",
    "_DomainRoutingHubPage",
    "_DomainPortsSectionPage",
    "_LocationsSectionPage",
    "_RedirectsSectionPage",
    "_BackendSectionPage",
    "_StaticSectionPage",
    "_SecuritySectionPage",
]


@pytest.mark.parametrize("name", REMOVED_PAGES)
def test_the_nested_config_pages_are_gone(name):
    assert not hasattr(commands, name)


@pytest.mark.parametrize(
    "name",
    ["_run_hidden_action", "_site_hub_menu", "_ssl_menu_item", "_on_off",
     "_security_preset_label", "_MenuItem"],
)
def test_their_helpers_went_with_them(name):
    assert not hasattr(commands, name)


def test_the_display_only_parser_layer_is_gone():
    """SiteConfigSections existed only to feed those pages."""
    from iw_agent.modules.nginx import collector, schemas

    assert not hasattr(schemas, "SiteConfigSections")
    assert not hasattr(collector, "load_site_config_sections")
    assert not hasattr(collector, "_main_server_block_lines")


def test_the_site_picker_loop_opens_the_editor():
    source = inspect.getsource(commands.run_nginx_interactive)

    assert "_interactive_pick_site" in source
    assert "_open_editor" in source
    assert "Navigator" not in source


def test_the_site_picker_uses_the_tui_cards():
    source = inspect.getsource(commands._interactive_pick_site)

    assert "pick_site" in source


def test_new_site_creation_opens_the_editor():
    source = inspect.getsource(commands._interactive_create_site)

    assert "_run_create_site_with_optional_https" in source
    assert "VirtualHost" in source


def test_there_is_one_interactive_entry_point():
    """Two ways into the same screen is the duplication we removed."""
    parser = build_parser()
    args = parser.parse_args(["nginx", "-i"])

    assert args.interactive is True
    assert not hasattr(args, "editor")


def test_site_can_be_opened_directly():
    parser = build_parser()
    args = parser.parse_args(["nginx", "-i", "--site", "demo.test"])

    assert args.site == "demo.test"


def test_interactive_with_a_site_skips_the_list(monkeypatch):
    called = {}

    async def fake_editor(args):
        called["site"] = args.site

    monkeypatch.setattr(commands, "run_nginx_editor", fake_editor)
    args = argparse.Namespace(site="demo.test", plain=True)
    asyncio.run(commands.run_nginx_interactive(args))

    assert called == {"site": "demo.test"}


def test_the_actions_the_deleted_pages_ran_are_still_registered():
    """Deleting the UI must not delete the programmatic surface."""
    from iw_agent.core.action_service import ActionService

    ids = {spec.id for module, spec in ActionService().list_actions() if module == "nginx"}
    assert {
        "apply_redirect_settings", "apply_backend_settings", "apply_security_settings",
        "apply_static_settings", "apply_domain_port_settings", "apply_location_settings",
        "create_site", "secure_site",
    } <= ids


def test_project_deploy_still_depends_on_those_actions():
    from iw_agent.modules.project import nginx_wiring

    source = inspect.getsource(nginx_wiring)
    for action_id in ("apply_backend_settings", "create_site", "secure_site"):
        assert f'action_id="{action_id}"' in source
