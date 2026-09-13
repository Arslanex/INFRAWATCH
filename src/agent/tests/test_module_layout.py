"""Guard against resurrecting the old ``ngnix`` typo package."""
from pathlib import Path

import iw_agent
from iw_agent.core.action_registry import collect_module_executors
from iw_agent.cli.registry import collect_command_specs

def _package_root() -> Path:
    if iw_agent.__file__:
        return Path(iw_agent.__file__).resolve().parent
    return Path(iw_agent.__path__[0]).resolve()


MODULES_ROOT = _package_root() / "modules"


def test_ngnix_typo_module_is_not_shipped():
    assert not (MODULES_ROOT / "ngnix").exists()
    assert (MODULES_ROOT / "nginx").is_dir()


def test_executors_use_nginx_not_ngnix():
    modules = {executor.module for executor in collect_module_executors()}
    assert "nginx" in modules
    assert "ngnix" not in modules


def test_cli_specs_use_nginx_not_ngnix():
    names = {spec.name for spec in collect_command_specs()}
    assert "nginx" in names
    assert "ngnix" not in names
