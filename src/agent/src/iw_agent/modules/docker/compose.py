from __future__ import annotations

from pathlib import Path

from iw_agent.core.commands import CommandResult, is_command_available, run_command

DEFAULT_COMPOSE_TIMEOUT = 600.0
COMPOSE_BINARY = "docker"


def compose_available() -> bool:
    return is_command_available(COMPOSE_BINARY)


def build_compose_argv(
    project_dir: Path,
    compose_file: str,
    project_name: str,
    *subcommand: str,
) -> list[str]:
    compose_path = project_dir / compose_file
    return [
        COMPOSE_BINARY,
        "compose",
        "-f",
        str(compose_path),
        "-p",
        project_name,
        *subcommand,
    ]


async def compose_up(
    project_dir: Path,
    compose_file: str,
    project_name: str,
    *,
    build: bool = True,
    dry_run: bool = False,
    timeout: float = DEFAULT_COMPOSE_TIMEOUT,
) -> tuple[list[str], CommandResult | None]:
    argv = build_compose_argv(project_dir, compose_file, project_name, "up", "-d")
    if build:
        argv.append("--build")
    if dry_run:
        return argv, None
    if not compose_available():
        raise RuntimeError("docker compose is not available")
    result = await run_command(argv, timeout=timeout, cwd=str(project_dir))
    return argv, result


async def compose_down(
    project_dir: Path,
    compose_file: str,
    project_name: str,
    *,
    dry_run: bool = False,
    timeout: float = DEFAULT_COMPOSE_TIMEOUT,
) -> tuple[list[str], CommandResult | None]:
    argv = build_compose_argv(project_dir, compose_file, project_name, "down")
    if dry_run:
        return argv, None
    if not compose_available():
        raise RuntimeError("docker compose is not available")
    result = await run_command(argv, timeout=timeout, cwd=str(project_dir))
    return argv, result


async def compose_ps(
    project_dir: Path,
    compose_file: str,
    project_name: str,
    *,
    timeout: float = 60.0,
) -> tuple[list[str], CommandResult | None]:
    argv = build_compose_argv(project_dir, compose_file, project_name, "ps")
    if not compose_available():
        raise RuntimeError("docker compose is not available")
    result = await run_command(argv, timeout=timeout, cwd=str(project_dir))
    return argv, result
