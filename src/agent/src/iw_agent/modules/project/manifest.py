from __future__ import annotations

import json
from pathlib import Path

from iw_agent.modules.project.schemas import ProjectManifest

MANIFEST_FILENAME = ".infrawatch.json"


def manifest_path(project_dir: Path) -> Path:
    return project_dir / MANIFEST_FILENAME


def load_manifest(project_dir: Path) -> ProjectManifest | None:
    path = manifest_path(project_dir)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ProjectManifest.model_validate(payload)


def save_manifest(project_dir: Path, manifest: ProjectManifest) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(project_dir)
    data = manifest.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def repo_dir(project_dir: Path) -> Path:
    return project_dir / "repo"
