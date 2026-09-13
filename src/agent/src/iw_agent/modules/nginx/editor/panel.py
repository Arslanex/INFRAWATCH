"""The actions panel — everything that is not a text edit.

These are the operations that used to sit behind the nested pages: test the
config, reload, enable or disable the site, obtain or renew a certificate.
They live one keypress away (`x`) instead of four menu levels down.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PanelAction:
    key: str
    label: str
    hint: str
    action_id: str = ""
    needs_email: bool = False
    destructive: bool = False
    local: bool = False


ACTIONS: tuple = (
    PanelAction("test", "Test config", "run nginx -t without changing anything",
                action_id="test_config"),
    PanelAction("reload", "Reload nginx", "apply the config that is on disk",
                action_id="reload"),
    PanelAction("enable", "Enable site", "symlink into sites-enabled, then reload",
                action_id="enable_site"),
    PanelAction("disable", "Disable site", "remove the symlink, then reload",
                action_id="disable_site", destructive=True),
    PanelAction("secure", "Obtain HTTPS certificate",
                "certbot, then wire the certificate in", action_id="secure_site",
                needs_email=True),
    PanelAction("renew", "Renew certificate", "certbot renew for this site",
                action_id="renew_site"),
    PanelAction("diff", "Show unsaved changes", "what would be written", local=True),
    PanelAction("revert", "Discard unsaved changes", "go back to the file on disk",
                local=True, destructive=True),
    PanelAction("reread", "Reload from disk", "pick up changes made elsewhere",
                local=True),
)


def available(*, dirty: bool) -> list:
    """Hide the buffer-only entries when there is nothing unsaved."""
    return [
        action
        for action in ACTIONS
        if not (action.key in {"diff", "revert"} and not dirty)
    ]
