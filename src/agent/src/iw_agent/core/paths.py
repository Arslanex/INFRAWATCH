"""Where the agent keeps its runtime state.

These used to be relative paths ("logs/actions.log", "projects"), which meant
the audit trail and the project workspace landed wherever the operator
happened to cd before running `sudo iw`. They are resolved here instead, once,
against the system directories a service would use -- with a writable fallback
so an unprivileged developer checkout still works.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_STATE_DIR = "INFRAWATCH_STATE_DIR"
ENV_DATA_DIR = "INFRAWATCH_DATA_DIR"
ENV_PROJECTS_DIR = "INFRAWATCH_PROJECTS_DIR"

SYSTEM_STATE_DIR = Path("/var/log/infrawatch")
SYSTEM_DATA_DIR = Path("/var/lib/infrawatch")


def _has_effective_root() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:  # non-POSIX
        return False


def _user_dir(xdg_var: str, fallback: str) -> Path:
    base = os.environ.get(xdg_var)
    if base:
        return Path(base).expanduser() / "infrawatch"
    return Path.home() / fallback / "infrawatch"


def _writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return os.access(path, os.W_OK)


def _resolve(env_var: str, system: Path, xdg_var: str, fallback: str) -> Path:
    override = os.environ.get(env_var)
    if override:
        return Path(override).expanduser().resolve()
    if _has_effective_root() and _writable(system):
        return system
    return _user_dir(xdg_var, fallback).resolve()


def state_dir() -> Path:
    """Logs and the audit trail."""
    return _resolve(ENV_STATE_DIR, SYSTEM_STATE_DIR, "XDG_STATE_HOME", ".local/state")


def data_dir() -> Path:
    """Project workspaces and other persistent data."""
    return _resolve(ENV_DATA_DIR, SYSTEM_DATA_DIR, "XDG_DATA_HOME", ".local/share")


def error_log_path() -> Path:
    return state_dir() / "error.log"


def audit_log_path() -> Path:
    return state_dir() / "actions.log"


def cron_log_dir() -> Path:
    return state_dir() / "cron"


def projects_dir() -> Path:
    override = os.environ.get(ENV_PROJECTS_DIR)
    if override:
        return Path(override).expanduser().resolve()
    return data_dir() / "projects"
