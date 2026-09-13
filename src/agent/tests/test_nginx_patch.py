"""Pure config-rewriting helpers from the nginx executor.

These run as root against real server configs, so they carry the most risk
in the agent and are the cheapest thing to pin down: string in, string out.
"""
import pytest

from iw_agent.modules.nginx.executor import (
    apply_redirect_settings_content,
    patch_backend_content,
    patch_config_content,
    patch_redirect_content,
    patch_www_redirect_content,
    remove_http_redirect_content,
    remove_www_redirect_content,
)

PROXY_SITE = """server {
    listen 80;
    server_name example.test;

    location / {
        proxy_pass http://127.0.0.1:3000;
    }
}
"""


# --- ssl directives -------------------------------------------------------

def test_patch_config_adds_ssl_directives():
    updated, changed, detail = patch_config_content(PROXY_SITE, "example.test")

    assert changed is True
    assert "ssl directives added" in detail
    assert "ssl_certificate /etc/letsencrypt/live/example.test/fullchain.pem;" in updated
    assert "ssl_certificate_key /etc/letsencrypt/live/example.test/privkey.pem;" in updated
    assert "listen 443 ssl;" in updated


def test_patch_config_honours_custom_live_dir():
    updated, changed, _ = patch_config_content(PROXY_SITE, "example.test", live_dir="/srv/certs")

    assert changed is True
    assert "ssl_certificate /srv/certs/example.test/fullchain.pem;" in updated


def test_patch_config_is_idempotent():
    once, _, _ = patch_config_content(PROXY_SITE, "example.test")
    twice, changed, detail = patch_config_content(once, "example.test")

    assert changed is False
    assert twice == once
    assert "already references" in detail


def test_patch_config_preserves_trailing_newline():
    updated, _, _ = patch_config_content(PROXY_SITE, "example.test")
    assert updated.endswith("\n")

    no_newline, _, _ = patch_config_content(PROXY_SITE.rstrip("\n"), "example.test")
    assert not no_newline.endswith("\n")


def test_patch_config_rejects_unknown_domain():
    with pytest.raises(ValueError, match="no server block"):
        patch_config_content(PROXY_SITE, "absent")


# --- http -> https redirect ----------------------------------------------

def test_patch_redirect_adds_block():
    updated, changed, _ = patch_redirect_content(PROXY_SITE, "example.test")

    assert changed is True
    assert "return 301 https://$host$request_uri;" in updated
    # the redirect block is prepended, the original server block survives
    assert updated.count("server {") == 2
    assert "proxy_pass http://127.0.0.1:3000;" in updated


def test_patch_redirect_is_idempotent():
    once, _, _ = patch_redirect_content(PROXY_SITE, "example.test")
    twice, changed, _ = patch_redirect_content(once, "example.test")

    assert changed is False
    assert twice == once


def test_remove_http_redirect_round_trips():
    with_redirect, _, _ = patch_redirect_content(PROXY_SITE, "example.test")
    removed, changed, _ = remove_http_redirect_content(with_redirect, "example.test")

    assert changed is True
    assert "return 301 https://$host$request_uri;" not in removed
    assert "proxy_pass http://127.0.0.1:3000;" in removed


def test_remove_http_redirect_when_absent_is_a_noop():
    removed, changed, detail = remove_http_redirect_content(PROXY_SITE, "example.test")

    assert changed is False
    assert removed == PROXY_SITE
    assert "not configured" in detail


# --- www -> apex redirect -------------------------------------------------

def test_patch_www_redirect_adds_block():
    updated, changed, _ = patch_www_redirect_content(PROXY_SITE, "example.test")

    assert changed is True
    assert "server_name www.example.test;" in updated
    assert "return 301 https://example.test$request_uri;" in updated


def test_remove_www_redirect_round_trips():
    with_www, _, _ = patch_www_redirect_content(PROXY_SITE, "example.test")
    removed, changed, _ = remove_www_redirect_content(with_www, "example.test")

    assert changed is True
    assert "server_name www.example.test;" not in removed


# --- combined redirect settings ------------------------------------------

def test_apply_redirect_settings_enables_both():
    updated, changed, messages = apply_redirect_settings_content(
        PROXY_SITE, "example.test", http_to_https=True, www_to_apex=True,
    )

    assert changed is True
    assert len(messages) == 2
    assert "return 301 https://$host$request_uri;" in updated
    assert "server_name www.example.test;" in updated


def test_apply_redirect_settings_none_means_leave_alone():
    updated, changed, messages = apply_redirect_settings_content(PROXY_SITE, "example.test")

    assert changed is False
    assert updated == PROXY_SITE
    assert messages == ["no redirect changes needed"]


def test_apply_redirect_settings_can_disable():
    both, _, _ = apply_redirect_settings_content(
        PROXY_SITE, "example.test", http_to_https=True, www_to_apex=True,
    )
    updated, changed, _ = apply_redirect_settings_content(
        both, "example.test", http_to_https=False, www_to_apex=False,
    )

    assert changed is True
    assert "return 301" not in updated


# --- backend (proxy_pass) -------------------------------------------------

def test_patch_backend_updates_proxy_pass():
    updated, changed, detail = patch_backend_content(
        PROXY_SITE, "example.test", proxy_pass="http://127.0.0.1:4000",
    )

    assert changed is True
    assert "proxy_pass updated" in detail
    assert "proxy_pass http://127.0.0.1:4000;" in updated
    assert "http://127.0.0.1:3000" not in updated




def test_patch_backend_to_same_value_is_a_noop():
    updated, changed, detail = patch_backend_content(
        PROXY_SITE, "example.test", proxy_pass="http://127.0.0.1:3000",
    )

    assert changed is False
    assert updated == PROXY_SITE
    assert "no backend changes needed" in detail


def test_patch_backend_keeps_surrounding_blank_lines():
    updated, changed, _ = patch_backend_content(
        PROXY_SITE, "example.test", proxy_pass="http://127.0.0.1:4000",
    )

    assert changed is True
    # only the proxy_pass line may differ from the original
    before = PROXY_SITE.splitlines()
    after = updated.splitlines()
    assert len(before) == len(after)
    assert [i for i, (b, a) in enumerate(zip(before, after)) if b != a] == [5]


def test_patch_backend_removes_only_the_targeted_line():
    updated, changed, _ = patch_backend_content(
        PROXY_SITE, "example.test", remove_proxy=True,
    )

    assert changed is True
    assert "proxy_pass" not in updated
    # the blank line after server_name must survive
    assert "\n\n" in updated
