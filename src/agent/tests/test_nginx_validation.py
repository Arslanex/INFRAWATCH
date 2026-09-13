"""The nginx executor must not trust request params.

Everything here ends up either in an argv that runs as root or verbatim
inside a server config, so these are the boundaries that matter once core
starts driving the executor over the wire.
"""
import os

import pytest

from iw_agent.modules.nginx.executor import NginxExecutorConfig, _validate_request_params
from iw_agent.modules.nginx.validation import (
    NginxValidationError,
    validate_binary,
    validate_config_path,
    validate_directive_value,
    validate_domain,
    validate_proxy_pass,
)
from iw_agent.core.actions import ActionRequest


def _request(**params):
    return ActionRequest(module="nginx", action_id="apply_backend_settings", params=params)


# --- binaries run as root -------------------------------------------------

@pytest.mark.parametrize("value", ["nginx", "certbot", "/usr/sbin/nginx", "/usr/local/bin/certbot"])
def test_accepted_binaries(value):
    assert validate_binary(value, name="nginx_binary") == value


@pytest.mark.parametrize(
    "value",
    [
        "/tmp/evil",             # attacker-writable directory
        "/home/user/nginx",      # outside the system bin dirs
        "sh -c id",              # smuggled arguments
        "nginx; id",
        "../nginx",
        "",
    ],
)
def test_rejected_binaries(value):
    with pytest.raises(NginxValidationError):
        validate_binary(value, name="nginx_binary")


def test_executor_config_rejects_a_planted_binary():
    with pytest.raises(NginxValidationError):
        NginxExecutorConfig.from_params({"nginx_binary": "/tmp/evil"})


def test_executor_config_keeps_valid_overrides():
    config = NginxExecutorConfig.from_params(
        {"nginx_binary": "/usr/sbin/nginx", "timeout": 5},
    )
    assert config.nginx_binary == "/usr/sbin/nginx"
    assert config.timeout == 5.0


def test_executor_config_rejects_directory_traversal():
    with pytest.raises(NginxValidationError):
        NginxExecutorConfig.from_params({"sites_available_dir": "/etc/nginx/../../tmp"})


# --- values spliced into a server block -----------------------------------

@pytest.mark.parametrize("value", ["example.test", "sub.example.co.uk", "Example.Test"])
def test_accepted_domains(value):
    assert validate_domain(value) == value.lower()


@pytest.mark.parametrize(
    "value",
    ["../../etc/passwd", "example.test;", "exa mple.test", "a" * 300, "", "exam{ple}.test"],
)
def test_rejected_domains(value):
    with pytest.raises(NginxValidationError):
        validate_domain(value)


@pytest.mark.parametrize(
    "value",
    [
        "http://x/;}server{listen 81;",   # closes the block and opens a new one
        "http://x/ # comment",
        "http://x\nroot /etc;",
        "$(id)",
    ],
)
def test_proxy_pass_rejects_config_injection(value):
    with pytest.raises(NginxValidationError):
        validate_proxy_pass(value)


def test_proxy_pass_accepts_real_upstreams():
    assert validate_proxy_pass("http://127.0.0.1:3000") == "http://127.0.0.1:3000"
    assert validate_proxy_pass("https://backend.internal/api") == "https://backend.internal/api"


@pytest.mark.parametrize("value", ["/var/www;", "/var/www\nroot /etc", "/var/www}", "  "])
def test_directive_values_reject_config_injection(value):
    with pytest.raises(NginxValidationError):
        validate_directive_value(value, name="document_root")


# --- config paths steer root-level writes ---------------------------------

def test_config_path_must_sit_under_an_allowed_root():
    # compared against the realpath: on macOS /etc is a symlink to /private/etc
    root = os.path.realpath("/etc/nginx")
    assert validate_config_path("/etc/nginx/sites-available/site").startswith(root)


@pytest.mark.parametrize("value", ["/etc/passwd", "/root/.ssh/authorized_keys", "relative/path"])
def test_config_path_rejects_paths_outside_nginx(value):
    with pytest.raises(NginxValidationError):
        validate_config_path(value)


# --- the executor entry point ---------------------------------------------

def test_request_validation_accepts_a_normal_request():
    _validate_request_params(
        _request(domain="example.test", proxy_pass="http://127.0.0.1:3000"),
    )


@pytest.mark.parametrize(
    "params",
    [
        {"domain": "../../etc/passwd"},
        {"proxy_pass": "http://x/;root /etc;"},
        {"document_root": "/var/www;}"},
        {"email": "not-an-email"},
        {"http_port": 99999},
        {"domain": "example.test", "server_names": ["ok.test", "bad;name"]},
    ],
)
def test_request_validation_rejects_hostile_params(params):
    with pytest.raises(NginxValidationError):
        _validate_request_params(_request(**params))
