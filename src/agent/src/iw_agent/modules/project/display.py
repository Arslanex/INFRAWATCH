"""User-facing labels for project list, picker, and action menus."""
from __future__ import annotations

from iw_agent.modules.project.schemas import ProjectKind, ProjectSummary


def project_status_label(project: ProjectSummary) -> str:
    """Plain-English status for list cards and hints."""
    if project.kind is ProjectKind.DOCKER_COMPOSE:
        if project.deploy_ok:
            count = project.containers_running
            suffix = f" ({count} container(s))" if count else ""
            return f"compose running{suffix}"
        return "compose not started — use Deploy"

    if project.kind is ProjectKind.STATIC:
        if project.deploy_ok and project.domain:
            return f"published · {project.domain}"
        if project.domain:
            return f"nginx site · {project.domain} (publish incomplete)"
        return "not published — publish static site with a domain"

    if project.kind is ProjectKind.PROXY:
        if project.deploy_ok and project.domain:
            return f"published · {project.domain}"
        if project.domain:
            return f"nginx wired · {project.domain} (publish incomplete)"
        return "not published — start your app, then Publish to web"

    if project.kind is ProjectKind.DOCKERFILE:
        return "dockerfile detected — deploy not supported yet"

    return "unknown project type — re-detect after adding compose or static files"


def primary_action_label(kind: ProjectKind) -> str:
    if kind is ProjectKind.DOCKER_COMPOSE:
        return "Deploy stack"
    if kind is ProjectKind.STATIC:
        return "Publish site"
    if kind is ProjectKind.PROXY:
        return "Publish to web"
    return "Deploy"


def primary_action_hint(kind: ProjectKind) -> str:
    if kind is ProjectKind.DOCKER_COMPOSE:
        return "docker compose up, optional nginx + HTTPS"
    if kind is ProjectKind.STATIC:
        return "nginx serves files from repo — domain required"
    if kind is ProjectKind.PROXY:
        return "nginx → localhost port (uvicorn, etc.) — app must already be running"
    return "deploy when project type is supported"


def publish_wizard_intro(kind: ProjectKind) -> str:
    if kind is ProjectKind.PROXY:
        return (
            "Your app must already listen locally (e.g. uvicorn on 127.0.0.1:8000). "
            "Publish wires nginx and optional HTTPS — it does not start the process."
        )
    if kind is ProjectKind.STATIC:
        return "Publish creates an nginx static site for this repo — domain required."
    if kind is ProjectKind.DOCKER_COMPOSE:
        return "Deploy runs docker compose, then optional nginx proxy and HTTPS."
    return "Follow the prompts for this project type."
