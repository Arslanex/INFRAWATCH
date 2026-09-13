from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

import httpx

from iw_agent.core.actions import ActionKind, ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.exceptions import DockerError, DockerTimeoutError, DockerUnavailableError
from iw_agent.modules.docker.collector import (
    DEFAULT_CONTAINER_LIMIT,
    DEFAULT_DOCKER_SOCKET_PATH,
    DEFAULT_REQUEST_TIMEOUT_SECONDS,
    DOCKER_ENGINE_BASE_URL,
    collect_containers,
    find_container,
)
from iw_agent.modules.docker.compose import (
    DEFAULT_COMPOSE_TIMEOUT,
    compose_down,
    compose_ps,
    compose_up,
)
from iw_agent.modules.docker.schemas import Container

MODULE = "docker"
DEFAULT_LOG_TAIL = 100

DOCKER_ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec(
        id="view_details",
        label="View container details",
        kind=ActionKind.READ,
        description="Show image, ports, compose labels, and status",
    ),
    ActionSpec(
        id="view_logs",
        label="View container logs",
        kind=ActionKind.READ,
        description="Show the last lines of stdout/stderr from the container",
    ),
    ActionSpec(
        id="start_container",
        label="Start container",
        kind=ActionKind.WRITE,
        description="POST /containers/{id}/start",
    ),
    ActionSpec(
        id="stop_container",
        label="Stop container",
        kind=ActionKind.WRITE,
        description="POST /containers/{id}/stop",
    ),
    ActionSpec(
        id="restart_container",
        label="Restart container",
        kind=ActionKind.WRITE,
        description="POST /containers/{id}/restart",
    ),
    ActionSpec(
        id="compose_up",
        label="Docker compose up",
        kind=ActionKind.WRITE,
        description="Run docker compose up -d for a project directory",
    ),
    ActionSpec(
        id="compose_down",
        label="Docker compose down",
        kind=ActionKind.WRITE,
        description="Run docker compose down for a project directory",
    ),
    ActionSpec(
        id="compose_ps",
        label="Docker compose ps",
        kind=ActionKind.READ,
        description="Run docker compose ps for a project directory",
    ),
)

DOCKER_ACTIONS_BY_ID = {action.id: action for action in DOCKER_ACTIONS}


class DockerExecutorConfig:
    def __init__(
        self,
        *,
        socket_path: str = DEFAULT_DOCKER_SOCKET_PATH,
        timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
        limit: int = DEFAULT_CONTAINER_LIMIT,
    ) -> None:
        self.socket_path = socket_path
        self.timeout = timeout
        self.limit = limit

    @classmethod
    def from_params(cls, params: dict) -> DockerExecutorConfig:
        return cls(
            socket_path=str(params.get("socket_path", DEFAULT_DOCKER_SOCKET_PATH)),
            timeout=float(params.get("timeout", DEFAULT_REQUEST_TIMEOUT_SECONDS)),
            limit=int(params.get("limit", DEFAULT_CONTAINER_LIMIT)),
        )


class DockerExecutor:
    module = MODULE

    def actions(self) -> tuple[ActionSpec, ...]:
        return DOCKER_ACTIONS

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        if request.action_id not in DOCKER_ACTIONS_BY_ID:
            return _fail(request, f"unknown docker action: {request.action_id}", options)

        handler = _HANDLERS.get(request.action_id)
        if handler is None:
            return _fail(request, f"handler missing for {request.action_id}", options)
        config = DockerExecutorConfig.from_params(request.params)
        return await handler(request, options, config=config)


def _fail(request: ActionRequest, message: str, options: ExecutorOptions) -> ActionResult:
    return ActionResult(
        ok=False,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        dry_run=options.dry_run,
    )


async def _resolve_container(
    request: ActionRequest,
    config: DockerExecutorConfig,
) -> Container | None:
    container_id = request.target_id or str(request.params.get("container_id") or "")
    if not container_id:
        return None
    return await find_container(
        container_id,
        socket_path=config.socket_path,
        timeout=config.timeout,
        limit=config.limit,
    )


def _format_container_details(container: Container) -> str:
    ports = ", ".join(str(port) for port in container.published_ports) or "-"
    lines = [
        f"name={container.container_name}",
        f"id={container.container_id[:12]}",
        f"state={container.state}",
        f"image={container.image_name}",
        f"ports={ports}",
    ]
    if container.compose_project_name:
        lines.append(f"compose_project={container.compose_project_name}")
    if container.compose_service_name:
        lines.append(f"compose_service={container.compose_service_name}")
    if container.status_message:
        lines.append(f"status={container.status_message}")
    if container.created_at:
        lines.append(f"created={container.created_at.isoformat()}")
    return "\n".join(lines)


async def _docker_request(
    method: str,
    path: str,
    *,
    config: DockerExecutorConfig,
    params: dict[str, Any] | None = None,
) -> httpx.Response:
    transport = httpx.AsyncHTTPTransport(uds=config.socket_path)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=DOCKER_ENGINE_BASE_URL,
        ) as client:
            response = await client.request(
                method,
                path,
                params=params,
                timeout=config.timeout,
            )
            response.raise_for_status()
            return response
    except httpx.TimeoutException as exc:
        raise DockerTimeoutError(
            f"docker API timed out after {config.timeout:.1f}s at {config.socket_path}",
        ) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise DockerUnavailableError(
            f"docker unavailable at {config.socket_path}: {exc}",
        ) from exc


def _decode_docker_logs(payload: bytes) -> str:
    if not payload:
        return ""

    if payload[0:1] not in {b"\x01", b"\x02"}:
        return payload.decode(errors="replace")

    chunks: list[str] = []
    offset = 0
    while offset + 8 <= len(payload):
        size = struct.unpack(">I", payload[offset + 4 : offset + 8])[0]
        offset += 8
        segment = payload[offset : offset + size]
        offset += size
        chunks.append(segment.decode(errors="replace"))
    return "".join(chunks)


async def _view_details(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    container = await _resolve_container(request, config)
    if container is None:
        return _fail(request, "container_id is required", options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=_format_container_details(container),
    )


async def _view_logs(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    container = await _resolve_container(request, config)
    if container is None:
        return _fail(request, "container_id is required", options)

    tail = int(request.params.get("tail", DEFAULT_LOG_TAIL))
    try:
        response = await _docker_request(
            "GET",
            f"/containers/{container.container_id}/logs",
            config=config,
            params={
                "stdout": 1,
                "stderr": 1,
                "tail": tail,
                "timestamps": 0,
            },
        )
    except DockerError as exc:
        return _fail(request, str(exc.message), options)

    text = _decode_docker_logs(response.content).strip()
    if not text:
        message = f"no log output (last {tail} lines)"
    else:
        message = text

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=message,
        stdout=text,
    )


async def _lifecycle_action(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
    action: str,
) -> ActionResult:
    container = await _resolve_container(request, config)
    if container is None:
        return _fail(request, "container_id is required", options)

    path = f"/containers/{container.container_id}/{action}"
    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would POST {path}",
            dry_run=True,
        )

    try:
        await _docker_request("POST", path, config=config)
    except DockerError as exc:
        return _fail(request, str(exc.message), options)

    return ActionResult(
        ok=True,
        module=MODULE,
        action_id=request.action_id,
        message=f"container {action}ed: {container.container_name}",
    )


async def _start_container(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    return await _lifecycle_action(
        request,
        options,
        config=config,
        action="start",
    )


async def _stop_container(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    return await _lifecycle_action(
        request,
        options,
        config=config,
        action="stop",
    )


async def _restart_container(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    return await _lifecycle_action(
        request,
        options,
        config=config,
        action="restart",
    )


def _compose_params(request: ActionRequest) -> tuple[str, str, str] | None:
    project_dir = str(request.params.get("project_dir") or request.target_id or "")
    compose_file = str(request.params.get("compose_file") or "docker-compose.yml")
    project_name = str(request.params.get("project_name") or "")
    if not project_dir or not project_name:
        return None
    return project_dir, compose_file, project_name


async def _compose_up(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    params = _compose_params(request)
    if params is None:
        return _fail(request, "project_dir and project_name are required", options)

    project_dir, compose_file, project_name = params
    build = bool(request.params.get("build", True))
    timeout = float(request.params.get("compose_timeout", DEFAULT_COMPOSE_TIMEOUT))

    try:
        argv, result = await compose_up(
            Path(project_dir),
            compose_file,
            project_name,
            build=build,
            dry_run=options.dry_run,
            timeout=timeout,
        )
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(argv)}",
            dry_run=True,
        )

    assert result is not None
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message="docker compose up finished" if result.ok else "docker compose up failed",
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _compose_down(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    params = _compose_params(request)
    if params is None:
        return _fail(request, "project_dir and project_name are required", options)

    project_dir, compose_file, project_name = params
    timeout = float(request.params.get("compose_timeout", DEFAULT_COMPOSE_TIMEOUT))

    try:
        argv, result = await compose_down(
            Path(project_dir),
            compose_file,
            project_name,
            dry_run=options.dry_run,
            timeout=timeout,
        )
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    if options.dry_run:
        return ActionResult(
            ok=True,
            module=MODULE,
            action_id=request.action_id,
            message=f"dry-run: would run {' '.join(argv)}",
            dry_run=True,
        )

    assert result is not None
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message="docker compose down finished" if result.ok else "docker compose down failed",
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def _compose_ps(
    request: ActionRequest,
    options: ExecutorOptions,
    *,
    config: DockerExecutorConfig,
) -> ActionResult:
    params = _compose_params(request)
    if params is None:
        return _fail(request, "project_dir and project_name are required", options)

    project_dir, compose_file, project_name = params
    timeout = float(request.params.get("compose_timeout", DEFAULT_COMPOSE_TIMEOUT))

    try:
        argv, result = await compose_ps(
            Path(project_dir),
            compose_file,
            project_name,
            timeout=timeout,
        )
    except RuntimeError as exc:
        return _fail(request, str(exc), options)

    assert result is not None
    text = result.stdout.strip() or result.stderr.strip() or "(no output)"
    return ActionResult(
        ok=result.ok,
        module=MODULE,
        action_id=request.action_id,
        message=text,
        stdout=result.stdout,
        stderr=result.stderr,
    )


async def count_running_compose_containers(
    project_name: str,
    *,
    socket_path: str = DEFAULT_DOCKER_SOCKET_PATH,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
) -> tuple[int, int]:
    containers = await collect_containers(socket_path=socket_path, timeout=timeout, limit=500)
    matched = [
        container
        for container in containers
        if container.compose_project_name == project_name
    ]
    running = sum(1 for container in matched if container.state.lower() == "running")
    return running, len(matched)


_HANDLERS = {
    "view_details": _view_details,
    "view_logs": _view_logs,
    "start_container": _start_container,
    "stop_container": _stop_container,
    "restart_container": _restart_container,
    "compose_up": _compose_up,
    "compose_down": _compose_down,
    "compose_ps": _compose_ps,
}
