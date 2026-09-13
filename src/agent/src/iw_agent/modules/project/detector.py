from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from iw_agent.modules.project.schemas import ProjectKind, ProjectProfile

COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)

STATIC_INDEX_CANDIDATES = (
    "index.html",
    "public/index.html",
    "dist/index.html",
    "build/index.html",
    "static/index.html",
)

COMPOSE_PORT_LINE = re.compile(
    r"^\s*-\s*"
    r"(?:[\"']?"
    r"(?:(?P<host_ip>\d+\.\d+\.\d+\.\d+):)?"
    r"(?P<host_port>\d+):(?P<container_port>\d+)"
    r"[\"']?"
    r"|"
    r"[\"']?(?P<only_port>\d+)[\"']?"
    r")\s*$",
)


def detect_project_profile(repo_path: Path) -> ProjectProfile:
    repo_path = repo_path.resolve()

    for filename in COMPOSE_FILENAMES:
        compose_path = repo_path / filename
        if compose_path.is_file():
            host_ports, container_ports = _parse_compose_ports(compose_path.read_text(errors="replace"))
            return ProjectProfile(
                kind=ProjectKind.DOCKER_COMPOSE,
                compose_file=filename,
                detected_ports=sorted(set(container_ports)),
                host_ports=sorted(set(host_ports)),
                suggested_backend_port=_suggest_backend_port(container_ports, host_ports),
                detected_at=datetime.now(timezone.utc),
            )

    dockerfile = repo_path / "Dockerfile"
    if dockerfile.is_file():
        return ProjectProfile(
            kind=ProjectKind.DOCKERFILE,
            dockerfile_path="Dockerfile",
            detected_at=datetime.now(timezone.utc),
        )

    static_root = _find_static_root(repo_path)
    if static_root is not None:
        return ProjectProfile(
            kind=ProjectKind.STATIC,
            static_root=static_root,
            detected_at=datetime.now(timezone.utc),
        )

    return ProjectProfile(
        kind=ProjectKind.PROXY,
        detected_at=datetime.now(timezone.utc),
    )


def _find_static_root(repo_path: Path) -> str | None:
    for candidate in STATIC_INDEX_CANDIDATES:
        if (repo_path / candidate).is_file():
            return str(Path(candidate).parent) if "/" in candidate else "."
    return None


def _parse_compose_ports(content: str) -> tuple[list[int], list[int]]:
    host_ports: list[int] = []
    container_ports: list[int] = []
    in_ports_block = False

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("ports:"):
            in_ports_block = True
            continue
        if in_ports_block:
            if stripped and not stripped.startswith("-") and not stripped.startswith("#"):
                if not line.startswith((" ", "\t")):
                    in_ports_block = False
                    continue
            match = COMPOSE_PORT_LINE.match(line)
            if match is None:
                continue
            if match.group("host_port") and match.group("container_port"):
                host_ports.append(int(match.group("host_port")))
                container_ports.append(int(match.group("container_port")))
            elif match.group("only_port"):
                port = int(match.group("only_port"))
                host_ports.append(port)
                container_ports.append(port)

    return host_ports, container_ports


def _suggest_backend_port(
    container_ports: list[int],
    host_ports: list[int],
) -> int | None:
    preferred = [3000, 8080, 8000, 5000, 4000, 8888]
    candidates = container_ports or host_ports
    for port in preferred:
        if port in candidates:
            return port
    return candidates[0] if candidates else None


def detection_hints(profile: ProjectProfile) -> list[str]:
    hints: list[str] = []
    if profile.kind is ProjectKind.DOCKER_COMPOSE:
        hints.append(f"Found {profile.compose_file} — deploy with docker compose (P2).")
        if profile.host_ports:
            hints.append(f"Compose publishes host ports: {', '.join(map(str, profile.host_ports))}.")
        if profile.suggested_backend_port:
            hints.append(
                f"Suggested backend port for nginx proxy: {profile.suggested_backend_port}.",
            )
    elif profile.kind is ProjectKind.DOCKERFILE:
        hints.append("Found Dockerfile — build and run container (P2).")
    elif profile.kind is ProjectKind.STATIC:
        root = profile.static_root or "."
        hints.append(f"Static site detected (root: {root}) — nginx static site fits.")
    elif profile.kind is ProjectKind.PROXY:
        hints.append(
            "No compose/Dockerfile/static index found — treat as proxy-only "
            "(nginx → existing localhost port).",
        )
    return hints
