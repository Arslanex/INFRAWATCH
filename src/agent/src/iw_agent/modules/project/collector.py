from __future__ import annotations

import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from iw_agent.core.commands import is_command_available, run_command
from iw_agent.core.exceptions import ProjectError
from iw_agent.core.paths import projects_dir
from iw_agent.modules.network.port_check import check_ports
from iw_agent.modules.project.detector import detect_project_profile, detection_hints
from iw_agent.modules.project.manifest import load_manifest, repo_dir, save_manifest
from iw_agent.modules.project.schemas import (
    DetectResult,
    ProjectManifest,
    ProjectSource,
    ProjectSummary,
)

DEFAULT_GIT_TIMEOUT = 120.0
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_GIT_URL_RE = re.compile(
    r"^(https?://|git@)[^\s]+(\.git)?$|^[a-z0-9._-]+@[a-z0-9.-]+:.+$",
    re.IGNORECASE,
)


def resolve_workspace_dir(workspace: str | None = None) -> Path:
    if workspace:
        return Path(workspace).expanduser().resolve()
    return projects_dir()


def validate_project_name(name: str) -> None:
    normalized = name.strip().lower()
    if not _NAME_RE.match(normalized):
        raise ProjectError(
            "project name must be 1-63 chars, lowercase letters, digits, or hyphens",
        )


def is_git_url(source: str) -> bool:
    return bool(_GIT_URL_RE.match(source.strip()))


def name_from_git_url(url: str) -> str:
    cleaned = url.strip().rstrip("/")
    if cleaned.endswith(".git"):
        cleaned = cleaned[:-4]
    if ":" in cleaned and "://" not in cleaned:
        cleaned = cleaned.rsplit(":", 1)[-1]
    else:
        cleaned = urlparse(cleaned).path.rstrip("/").split("/")[-1]
    return cleaned.lower()


async def list_projects(workspace: str | None = None) -> list[ProjectSummary]:
    root = resolve_workspace_dir(workspace)
    if not root.is_dir():
        return []

    summaries: list[ProjectSummary] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        manifest = load_manifest(entry)
        if manifest is None:
            continue
        profile = manifest.profile
        summaries.append(
            ProjectSummary(
                name=manifest.name,
                kind=profile.kind,
                source_type=manifest.source.type,
                repo_path=str(repo_dir(entry)),
                suggested_backend_port=profile.suggested_backend_port,
                host_ports=profile.host_ports,
                deploy_ok=manifest.deploy.last_deploy_ok,
                containers_running=manifest.deploy.containers_running,
            )
        )
    return summaries


async def add_project(
    source: str,
    *,
    name: str | None = None,
    workspace: str | None = None,
    git_timeout: float = DEFAULT_GIT_TIMEOUT,
) -> ProjectManifest:
    root = resolve_workspace_dir(workspace)
    root.mkdir(parents=True, exist_ok=True)

    if is_git_url(source):
        project_name = (name or name_from_git_url(source)).lower()
        validate_project_name(project_name)
        project_dir = root / project_name
        if project_dir.exists():
            raise ProjectError(f"project already exists: {project_name}")
        destination = repo_dir(project_dir)
        destination.parent.mkdir(parents=True, exist_ok=False)
        if not is_command_available("git"):
            raise ProjectError("git is not installed")
        result = await run_command(
            ["git", "clone", source.strip(), str(destination)],
            timeout=git_timeout,
        )
        if not result.ok:
            if destination.exists():
                shutil.rmtree(destination.parent, ignore_errors=True)
            message = result.stderr.strip() or result.stdout.strip() or "git clone failed"
            raise ProjectError(message)
        project_source = ProjectSource(type="git", url=source.strip())
    else:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_dir():
            raise ProjectError(f"local path not found: {source}")
        project_name = (name or source_path.name).lower()
        validate_project_name(project_name)
        project_dir = root / project_name
        if project_dir.exists():
            raise ProjectError(f"project already exists: {project_name}")
        project_dir.mkdir(parents=True)
        destination = repo_dir(project_dir)
        destination.symlink_to(source_path, target_is_directory=True)
        project_source = ProjectSource(type="local", path=str(source_path))

    profile = detect_project_profile(destination)
    manifest = ProjectManifest(
        name=project_name,
        source=project_source,
        workspace_path=str(project_dir),
        repo_path=str(destination),
        created_at=datetime.now(timezone.utc),
        profile=profile,
    )
    save_manifest(project_dir, manifest)
    return manifest


async def detect_project(
    name: str,
    *,
    workspace: str | None = None,
    save: bool = False,
) -> DetectResult:
    project_dir = _project_dir(name, workspace)
    manifest = load_manifest(project_dir)
    if manifest is None:
        raise ProjectError(f"project not found: {name}")

    repo = repo_dir(project_dir)
    if not repo.exists():
        raise ProjectError(f"repo path missing for project {name}: {repo}")

    profile = detect_project_profile(repo)
    ports_to_check = sorted(set(profile.host_ports + profile.detected_ports))
    if profile.suggested_backend_port is not None:
        ports_to_check.append(profile.suggested_backend_port)
    port_checks = await check_ports(ports_to_check)

    if save:
        manifest.profile = profile
        save_manifest(project_dir, manifest)

    return DetectResult(
        name=manifest.name,
        repo_path=str(repo),
        profile=profile,
        port_checks=port_checks,
        hints=detection_hints(profile),
    )


def _project_dir(name: str, workspace: str | None) -> Path:
    validate_project_name(name)
    return resolve_workspace_dir(workspace) / name.lower()
