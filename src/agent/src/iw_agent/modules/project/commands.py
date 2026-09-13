from __future__ import annotations

import argparse
import sys

from iw_agent.cli.output import (
    emit_json,
    emit_models,
    format_field,
    format_fields,
    print_empty,
    print_group_heading,
    print_info_box,
    print_insight,
    print_report,
    print_status_box,
    status_badge,
)
from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.parser import add_interactive_flags, add_timeout_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.actions import ActionRequest, ExecutorOptions
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError, ProjectError
from iw_agent.modules.project.collector import (
    DEFAULT_GIT_TIMEOUT,
    add_project,
    detect_project,
    list_projects,
    resolve_workspace_dir,
)
from iw_agent.modules.project.interactive import run_project_interactive
from iw_agent.modules.project.display import project_status_label
from iw_agent.modules.project.schemas import DetectResult, ProjectKind, ProjectSummary


async def run_project(args: argparse.Namespace) -> None:
    if getattr(args, "interactive", False):
        await run_project_interactive(args)
        return

    action = getattr(args, "project_action", None) or "list"
    if action == "list":
        await _run_project_list(args)
    elif action in {"add", "register"}:
        await _run_project_add(args)
    elif action == "detect":
        await _run_project_detect(args)
    elif action in {"deploy", "publish"}:
        await _run_project_deploy(args)
    elif action == "stop":
        await _run_project_stop(args)
    else:
        raise ProjectError(f"unknown project action: {action}")


async def _run_project_list(args: argparse.Namespace) -> None:
    projects = await list_projects(args.workspace)
    emit_models(projects, json_output=args.json, plain=args.plain, render=_render_projects)


async def _run_project_add(args: argparse.Namespace) -> None:
    try:
        manifest = await add_project(
            args.source,
            name=args.name,
            workspace=args.workspace,
            git_timeout=args.timeout,
        )
    except ProjectError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        emit_json(manifest.model_dump(mode="json"))
        return

    detect = await detect_project(manifest.name, workspace=args.workspace, save=False)
    print_report("Project added", manifest.name)
    print_insight(
        f"Saved to {manifest.workspace_path} · detected {manifest.profile.kind.value}",
    )
    _render_detect_summary(detect)


async def _run_project_action(args: argparse.Namespace, action_id: str) -> None:
    request = ActionRequest(
        module="project",
        action_id=action_id,
        target_id=args.name,
        params={
            "name": args.name,
            "workspace": args.workspace,
            "build": not getattr(args, "no_build", False),
            "force": getattr(args, "force", False),
            "compose_timeout": getattr(args, "timeout", 600.0),
            "domain": getattr(args, "domain", None),
            "https": getattr(args, "https", False),
            "email": getattr(args, "email", None),
            "include_www": not getattr(args, "no_www", False),
            "staging": getattr(args, "staging", False),
            "backend_port": getattr(args, "backend_port", None),
        },
    )
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    try:
        result = await run_action_with_prompts(
            request,
            options=options,
            target_label=args.name,
        )
    except ActionCancelledError:
        print("\nCancelled.")
        raise SystemExit(1)
    except ActionDeniedError as exc:
        print(f"\n{exc.message}", file=sys.stderr)
        raise SystemExit(1)

    if args.json:
        emit_json(
            {
                "ok": result.ok,
                "message": result.message,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "dry_run": result.dry_run,
            }
        )
        return

    print_report(f"Project {action_id.replace('_', ' ')}", args.name)
    print_action_result(result)
    if not result.ok:
        raise SystemExit(1)


async def _run_project_deploy(args: argparse.Namespace) -> None:
    await _run_project_action(args, "deploy_project")


async def _run_project_stop(args: argparse.Namespace) -> None:
    await _run_project_action(args, "stop_project")


async def _run_project_detect(args: argparse.Namespace) -> None:
    try:
        result = await detect_project(
            args.name,
            workspace=args.workspace,
            save=args.save,
        )
    except ProjectError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        raise SystemExit(1) from exc

    if args.json:
        emit_json(result.model_dump(mode="json"))
        return

    print_report("Project detection", result.name)
    _render_detect_summary(result)
    if args.save:
        print("\nDetection saved to .infrawatch.json")


def _projects_summary(projects: list[ProjectSummary]) -> str:
    if not projects:
        return "No registered projects."
    kinds = {project.kind.value for project in projects}
    return f"{len(projects)} project(s) registered · types: {', '.join(sorted(kinds))}"


def _kind_badge(kind: ProjectKind) -> tuple[str, str]:
    if kind is ProjectKind.DOCKER_COMPOSE:
        return status_badge("COMPOSE", "work"), "work"
    if kind is ProjectKind.DOCKERFILE:
        return status_badge("DOCKERFILE", "work"), "work"
    if kind is ProjectKind.STATIC:
        return status_badge("STATIC", "ok"), "ok"
    if kind is ProjectKind.PROXY:
        return status_badge("PROXY", "warn"), "warn"
    return status_badge("UNKNOWN", "off"), "off"


def _render_project_card(project: ProjectSummary) -> None:
    badge, tone = _kind_badge(project.kind)
    lines = [
        format_field("Type", project.kind.value),
        format_field("Source", project.source_type),
        format_field("Repo", project.repo_path),
    ]
    if project.suggested_backend_port is not None:
        lines.append(format_field("Backend port", str(project.suggested_backend_port)))
    if project.host_ports:
        lines.append(format_field("Host ports", ", ".join(map(str, project.host_ports))))
    lines.append(format_field("Status", project_status_label(project)))
    if project.domain:
        lines.append(format_field("Domain", project.domain))

    print_status_box(
        badge=badge,
        title=project.name,
        lines=lines,
        tone=tone,
    )


def _render_projects(projects: list[ProjectSummary]) -> None:
    workspace = resolve_workspace_dir()
    print_report("Registered projects", f"Workspace: {workspace}")
    if not projects:
        print_empty(
            "no projects",
            "No projects are registered yet.",
            "register: iw project register /path/to/existing-clone --name myapp",
        )
        return

    print_insight(_projects_summary(projects))
    print_info_box(
        title="Workflow",
        hint="by project type",
        lines=format_fields(
            [
                ("Register", "iw project register /path/or/git-url --name myapp"),
                (
                    "docker-compose",
                    "iw project deploy myapp [--domain …]  ·  stop: iw project stop myapp",
                ),
                (
                    "proxy (uvicorn, etc.)",
                    "start app locally, then: iw project publish myapp "
                    "--domain … --backend-port …",
                ),
                (
                    "Re-detect",
                    "only after repo layout changes: iw project detect myapp --save",
                ),
            ]
        ),
    )
    for project in projects:
        _render_project_card(project)


def _render_detect_summary(result: DetectResult) -> None:
    profile = result.profile
    print_group_heading("Detection", profile.kind.value)
    lines = [
        format_field("Repo", result.repo_path),
        format_field("Kind", profile.kind.value),
    ]
    if profile.compose_file:
        lines.append(format_field("Compose file", profile.compose_file))
    if profile.dockerfile_path:
        lines.append(format_field("Dockerfile", profile.dockerfile_path))
    if profile.static_root is not None:
        lines.append(format_field("Static root", profile.static_root))
    if profile.detected_ports:
        lines.append(format_field("Container ports", ", ".join(map(str, profile.detected_ports))))
    if profile.host_ports:
        lines.append(format_field("Host ports", ", ".join(map(str, profile.host_ports))))
    if profile.suggested_backend_port is not None:
        lines.append(format_field("Suggested backend", str(profile.suggested_backend_port)))

    badge, tone = _kind_badge(profile.kind)
    print_status_box(badge=badge, title=result.name, lines=lines, tone=tone)

    if result.hints:
        print_info_box(
            title="Hints",
            hint="next phases",
            lines=[format_field("Tip", hint) for hint in result.hints],
        )

    if result.port_checks:
        print_group_heading("Port check", "listeners on this server")
        for check in result.port_checks:
            badge_label = "FREE" if check.available else "IN USE"
            badge_tone = "ok" if check.available else "bad"
            check_lines = [format_field("Note", check.note)]
            if check.listener:
                check_lines.append(format_field("Listener", check.listener))
            print_status_box(
                badge=status_badge(badge_label, badge_tone),
                title=f"port {check.port}",
                lines=check_lines,
                tone=badge_tone,
            )


def _configure(parser: argparse.ArgumentParser) -> None:
    add_interactive_flags(parser)
    parser.add_argument(
        "--workspace",
        default=None,
        help="projects workspace directory (default: projects or $INFRAWATCH_PROJECTS_DIR)",
    )
    subparsers = parser.add_subparsers(dest="project_action")

    subparsers.add_parser("list", help="list registered projects")

    def _configure_register_parser(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "source",
            help="git URL or path to an existing local clone",
        )
        subparser.add_argument(
            "--name",
            default=None,
            help="project name (default: repo or directory name)",
        )
        add_timeout_flag(subparser, default=DEFAULT_GIT_TIMEOUT)

    add_parser = subparsers.add_parser(
        "add",
        help="register project (alias: register)",
    )
    _configure_register_parser(add_parser)

    register_parser = subparsers.add_parser(
        "register",
        help="register existing clone or clone from git (preferred name)",
    )
    _configure_register_parser(register_parser)

    detect_parser = subparsers.add_parser(
        "detect",
        help="re-detect project type and ports (after repo layout changes)",
    )
    detect_parser.add_argument("name", help="registered project name")
    detect_parser.add_argument(
        "--save",
        action="store_true",
        help="write detection results to .infrawatch.json",
    )

    stop_parser = subparsers.add_parser("stop", help="stop a docker-compose project")
    stop_parser.add_argument("name", help="registered project name")
    add_interactive_flags(stop_parser)
    add_timeout_flag(stop_parser, default=600.0)

    def _configure_publish_parser(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("name", help="registered project name")
        add_interactive_flags(subparser)
        add_timeout_flag(subparser, default=600.0)
        subparser.add_argument(
            "--no-build",
            action="store_true",
            help="skip docker compose --build (compose projects only)",
        )
        subparser.add_argument(
            "--force",
            action="store_true",
            help="continue even if ports look busy or backend is not listening",
        )
        subparser.add_argument(
            "--domain",
            default=None,
            help="public domain for nginx (required for proxy/static publish)",
        )
        subparser.add_argument(
            "--https",
            action="store_true",
            help="obtain Let's Encrypt certificate after nginx site is ready",
        )
        subparser.add_argument(
            "--email",
            default=None,
            help="contact email for Let's Encrypt (required with --https)",
        )
        subparser.add_argument(
            "--no-www",
            action="store_true",
            help="do not add www.<domain> to server_name",
        )
        subparser.add_argument(
            "--backend-port",
            type=int,
            default=None,
            help="local port for proxy_pass (proxy apps — e.g. uvicorn on 8000)",
        )

    deploy_parser = subparsers.add_parser(
        "deploy",
        help="deploy docker-compose stack (alias: publish for all types)",
    )
    _configure_publish_parser(deploy_parser)

    publish_parser = subparsers.add_parser(
        "publish",
        help="publish via nginx (proxy/static) or deploy compose — preferred name",
    )
    _configure_publish_parser(publish_parser)


COMMAND_SPECS = [
    CliCommandSpec("project", "manage deployable projects", run_project, _configure),
]
