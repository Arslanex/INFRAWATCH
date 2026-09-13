"""The whole-config write path: the only place the editor touches disk.

Every failure mode here ends with a root-owned nginx config on a real server,
so each one is pinned.
"""
import asyncio
import os
import pathlib

import pytest

import iw_agent.core.executor_runtime as executor_runtime
import iw_agent.modules.nginx.executor as nginx_executor
from iw_agent.core.action_service import ActionService
from iw_agent.core.actions import ActionRequest, ExecutorOptions
from iw_agent.core.commands import CommandResult
from iw_agent.modules.nginx import safe_write

ORIGINAL = """server {
    listen 80;
    server_name demo.test;

    location / {
        proxy_pass http://127.0.0.1:3000;
    }
}
"""

EDITED = ORIGINAL.replace("3000", "4000")


def _result(ok: bool, stderr: str = "") -> CommandResult:
    return CommandResult(
        argv=("nginx", "-t"),
        exit_code=0 if ok else 1,
        stdout="",
        stderr=stderr,
    )


@pytest.fixture
def site(tmp_path, monkeypatch):
    available = tmp_path / "sites-available"
    available.mkdir()
    config = available / "demo.test"
    config.write_text(ORIGINAL, encoding="utf-8")

    monkeypatch.setattr(executor_runtime, "has_effective_root", lambda: True)
    monkeypatch.setattr(nginx_executor, "is_command_available", lambda _binary: True)

    return {"path": config, "available": available}


def _write(site, content, *, dry_run=False, sha=None, tests=None, reload=False):
    """Drive the action, with nginx -t answers supplied as a queue."""
    answers = list(tests if tests is not None else [_result(True), _result(True)])

    async def fake_run_command(argv, timeout, cwd=None):
        return answers.pop(0) if answers else _result(True)

    import unittest.mock as mock

    params = {
        "content": content,
        "sites_available_dir": str(site["available"]),
        "reload": reload,
    }
    if sha is not None:
        params["expected_sha256"] = sha

    request = ActionRequest(
        module="nginx",
        action_id="write_site_config",
        target_id=str(site["path"]),
        params=params,
    )
    with mock.patch.object(nginx_executor, "run_command", fake_run_command):
        return asyncio.run(
            ActionService().run(
                request,
                options=ExecutorOptions(dry_run=dry_run, skip_confirm=True,
                                        audit_log_path=str(site["path"].parent / "audit.log")),
            )
        )


# --- happy path -----------------------------------------------------------

def test_writes_the_new_content(site):
    result = _write(site, EDITED)

    assert result.ok is True
    assert "nginx -t passed" in result.message
    assert site["path"].read_text(encoding="utf-8") == EDITED


def test_identical_content_is_a_no_op(site):
    result = _write(site, ORIGINAL)

    assert result.ok is True
    assert result.message == "no changes"
    assert not (site["path"].parent / "demo.test.iw.prev").exists()


def test_reload_is_opt_in(site):
    result = _write(site, EDITED)
    assert "reloaded" not in result.message

    site["path"].write_text(ORIGINAL, encoding="utf-8")
    result = _write(site, EDITED, reload=True,
                    tests=[_result(True), _result(True), _result(True)])
    assert "nginx reloaded" in result.message


# --- dry run --------------------------------------------------------------

def test_dry_run_returns_a_diff_and_writes_nothing(site):
    result = _write(site, EDITED, dry_run=True)

    assert result.ok is True
    assert result.dry_run is True
    assert "-        proxy_pass http://127.0.0.1:3000;" in result.stdout
    assert "+        proxy_pass http://127.0.0.1:4000;" in result.stdout
    assert site["path"].read_text(encoding="utf-8") == ORIGINAL


# --- optimistic locking ---------------------------------------------------

def test_stale_revision_is_refused(site):
    stale = safe_write.sha256_text("something else entirely")
    result = _write(site, EDITED, sha=stale)

    assert result.ok is False
    assert "changed on disk" in result.message
    assert site["path"].read_text(encoding="utf-8") == ORIGINAL


def test_matching_revision_is_accepted(site):
    result = _write(site, EDITED, sha=safe_write.sha256_text(ORIGINAL))

    assert result.ok is True
    assert site["path"].read_text(encoding="utf-8") == EDITED


# --- rollback -------------------------------------------------------------

def test_rejected_config_is_rolled_back_byte_for_byte(site):
    result = _write(
        site,
        EDITED,
        tests=[_result(True), _result(False, "nginx: [emerg] bad thing")],
    )

    assert result.ok is False
    assert "rolled back" in result.message
    assert "bad thing" in result.stderr
    assert site["path"].read_text(encoding="utf-8") == ORIGINAL


def test_a_pre_existing_failure_does_not_discard_the_edit(site):
    """nginx -t covers the whole server; another broken site is not our fault."""
    result = _write(
        site,
        EDITED,
        tests=[_result(False, "other site broken"), _result(False, "other site broken")],
    )

    assert result.ok is False
    assert "already failing" in result.message
    assert site["path"].read_text(encoding="utf-8") == EDITED     # kept


def test_backups_are_written(site):
    _write(site, EDITED)

    pristine = site["path"].parent / "demo.test.iw.bak"
    rollback = site["path"].parent / "demo.test.iw.prev"
    assert pristine.read_text(encoding="utf-8") == ORIGINAL
    assert rollback.read_text(encoding="utf-8") == ORIGINAL


def test_pristine_backup_keeps_the_first_original(site):
    _write(site, EDITED)
    _write(site, EDITED.replace("4000", "5000"))

    pristine = site["path"].parent / "demo.test.iw.bak"
    rollback = site["path"].parent / "demo.test.iw.prev"
    assert pristine.read_text(encoding="utf-8") == ORIGINAL       # first ever
    assert rollback.read_text(encoding="utf-8") == EDITED         # previous


# --- content and path gates ----------------------------------------------

@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("server {\n    listen 80;\n", "unclosed"),
        ("server {\n}\n}\n", "unexpected"),
        ("   \n", "empty"),
    ],
)
def test_malformed_content_is_refused_before_touching_disk(site, content, expected):
    result = _write(site, content)

    assert result.ok is False
    assert expected in result.message
    assert site["path"].read_text(encoding="utf-8") == ORIGINAL


def test_path_outside_the_allowed_roots_is_refused(site, tmp_path):
    outside = tmp_path / "elsewhere.conf"
    outside.write_text(ORIGINAL, encoding="utf-8")

    request = ActionRequest(
        module="nginx",
        action_id="write_site_config",
        target_id=str(outside),
        params={"content": EDITED, "sites_available_dir": str(site["available"])},
    )
    result = asyncio.run(
        ActionService().run(
            request,
            options=ExecutorOptions(skip_confirm=True,
                                    audit_log_path=str(tmp_path / "audit.log")),
        )
    )

    assert result.ok is False
    assert "allowed nginx roots" in result.message
    assert outside.read_text(encoding="utf-8") == ORIGINAL


# --- atomicity ------------------------------------------------------------

def test_file_mode_survives_the_replace(site):
    os.chmod(site["path"], 0o640)
    _write(site, EDITED)

    assert site["path"].stat().st_mode & 0o777 == 0o640


def test_no_temporary_files_are_left_behind(site):
    _write(site, EDITED)

    leftovers = [p.name for p in site["available"].iterdir() if "iw-tmp" in p.name]
    assert leftovers == []


def test_write_is_atomic_not_truncating(site, monkeypatch):
    """A failure mid-write must leave the original intact, not a half file."""
    real_replace = os.replace

    def explode(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(safe_write.os, "replace", explode)
    with pytest.raises(OSError):
        safe_write.atomic_write(site["path"], EDITED)
    monkeypatch.setattr(safe_write.os, "replace", real_replace)

    assert site["path"].read_text(encoding="utf-8") == ORIGINAL
    assert [p.name for p in site["available"].iterdir() if "iw-tmp" in p.name] == []


# --- audit ----------------------------------------------------------------

def test_the_write_produces_one_audit_entry(site):
    import json

    _write(site, EDITED)
    log = site["path"].parent / "audit.log"
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    writes = [e for e in entries if e["action_id"] == "write_site_config"]

    assert len(writes) == 1
    assert writes[0]["ok"] is True
    assert "+1/-1 lines" in writes[0]["message"]
    assert EDITED not in writes[0]["message"]          # never log file content
