"""End-to-end cover for the project deploy chain.

Regression for two bugs that only showed up at runtime:
  * ActionResult.stdout/stderr were None for non-compose projects
  * nested nginx actions were dispatched with options as a positional arg
"""
import asyncio
import json
from datetime import datetime, timezone

import pytest

import iw_agent.core.executor_runtime as executor_runtime
from iw_agent.core.action_service import ActionService
from iw_agent.core.actions import ActionRequest, ExecutorOptions


@pytest.fixture
def static_project(tmp_path, monkeypatch):
    """A registered static project plus an isolated fake nginx tree."""
    workspace = tmp_path / "projects"
    repo = workspace / "demo" / "repo"
    repo.mkdir(parents=True)
    (repo / "index.html").write_text("<h1>demo</h1>", encoding="utf-8")

    manifest = {
        "name": "demo",
        "source": {"type": "local", "path": str(repo)},
        "workspace_path": str(workspace / "demo"),
        "repo_path": str(repo),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (workspace / "demo" / ".infrawatch.json").write_text(json.dumps(manifest), encoding="utf-8")

    sites_available = tmp_path / "nginx" / "sites-available"
    sites_enabled = tmp_path / "nginx" / "sites-enabled"
    sites_available.mkdir(parents=True)
    sites_enabled.mkdir(parents=True)

    # creating a site is a root action; the fake tree is writable either way
    monkeypatch.setattr(executor_runtime, "has_effective_root", lambda: True)

    return {
        "workspace": str(workspace),
        "sites_available_dir": str(sites_available),
        "sites_enabled_dir": str(sites_enabled),
        "_sites_available": sites_available,
    }


def _deploy(params, *, dry_run, audit_log):
    request = ActionRequest(
        module="project",
        action_id="deploy_project",
        target_id="demo",
        params=params,
    )
    return asyncio.run(
        ActionService().run(
            request,
            options=ExecutorOptions(
                dry_run=dry_run, skip_confirm=True, audit_log_path=str(audit_log),
            ),
        )
    )


def test_dry_run_deploy_reports_success_without_touching_disk(static_project, tmp_path):
    params = {k: v for k, v in static_project.items() if not k.startswith("_")}
    params["domain"] = "demo.test"

    result = _deploy(params, dry_run=True, audit_log=tmp_path / "actions.log")

    assert result.ok is True
    assert result.dry_run is True
    assert "would create" in result.message
    assert not list(static_project["_sites_available"].iterdir())


def test_deploy_result_stdout_and_stderr_are_always_strings(static_project, tmp_path):
    """Static projects never run compose, so these stayed None and broke validation."""
    params = {k: v for k, v in static_project.items() if not k.startswith("_")}
    params["domain"] = "demo.test"

    result = _deploy(params, dry_run=True, audit_log=tmp_path / "actions.log")

    assert isinstance(result.stdout, str)
    assert isinstance(result.stderr, str)


def test_deploy_writes_the_nginx_site(static_project, tmp_path):
    params = {k: v for k, v in static_project.items() if not k.startswith("_")}
    params["domain"] = "demo.test"

    _deploy(params, dry_run=False, audit_log=tmp_path / "actions.log")

    config = static_project["_sites_available"] / "demo.test"
    assert config.is_file()
    content = config.read_text(encoding="utf-8")
    assert "server_name demo.test www.demo.test;" in content
    assert "index index.html index.htm;" in content


def test_deploy_without_domain_is_rejected_for_static_projects(static_project, tmp_path):
    params = {k: v for k, v in static_project.items() if not k.startswith("_")}

    result = _deploy(params, dry_run=True, audit_log=tmp_path / "actions.log")

    assert result.ok is False
    assert "requires --domain" in result.message


def test_deploy_is_written_to_the_audit_log(static_project, tmp_path):
    params = {k: v for k, v in static_project.items() if not k.startswith("_")}
    params["domain"] = "demo.test"
    audit_log = tmp_path / "actions.log"

    _deploy(params, dry_run=True, audit_log=audit_log)

    entries = [json.loads(line) for line in audit_log.read_text(encoding="utf-8").splitlines()]
    deploys = [e for e in entries if e["action_id"] == "deploy_project"]
    assert len(deploys) == 1
    assert deploys[0]["dry_run"] is True
    assert deploys[0]["module"] == "project"
