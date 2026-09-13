from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from iw_agent.core.exceptions import DockerError, DockerTimeoutError, DockerUnavailableError
from iw_agent.core.logger import logger
from iw_agent.modules.docker.schemas import Container, PublishedPort

DOCKER_ENGINE_BASE_URL = "http://docker"
CONTAINER_LIST_PATH = "/containers/json?all=1"
COMPOSE_PROJECT_LABEL = "com.docker.compose.project"
COMPOSE_SERVICE_LABEL = "com.docker.compose.service"

DEFAULT_DOCKER_SOCKET_PATH = "/var/run/docker.sock"
DEFAULT_REQUEST_TIMEOUT_SECONDS = 5.0
DEFAULT_CONTAINER_LIMIT = 200


async def collect_containers(
    socket_path: str = DEFAULT_DOCKER_SOCKET_PATH,
    timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    limit: int = DEFAULT_CONTAINER_LIMIT,
) -> list[Container]:
    # 1. Docker Engine API'den container listesini al
    try:
        payload = await _fetch_container_payload(socket_path, timeout)
    except DockerError as exc:
        logger.debug("%s", exc)
        return []

    # 2. API yanıtını modele dönüştür
    containers = [
        _container_from_api(container_payload)
        for container_payload in payload
    ]

    # 3. Önce running, sonra en yeni olacak şekilde sırala
    containers.sort(
        key=lambda container: (
            container.state != "running",
            -(
                container.created_at.timestamp()
                if container.created_at
                else 0
            ),
        )
    )

    # 4. Limitle
    if len(containers) > limit:
        logger.debug(
            "container list capped at %d of %d",
            limit,
            len(containers),
        )
        containers = containers[:limit]

    logger.debug("collected %d containers", len(containers))
    return containers


async def _fetch_container_payload(
    socket_path: str,
    timeout: float,
) -> list[dict[str, Any]]:
    transport = httpx.AsyncHTTPTransport(uds=socket_path)

    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=DOCKER_ENGINE_BASE_URL,
        ) as client:
            response = await client.get(CONTAINER_LIST_PATH, timeout=timeout)
            response.raise_for_status()
            return response.json()
    except httpx.TimeoutException as exc:
        raise DockerTimeoutError(
            f"docker API timed out after {timeout:.1f}s at {socket_path}"
        ) from exc
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise DockerUnavailableError(
            f"docker unavailable at {socket_path}: {exc}"
        ) from exc


def _container_from_api(container_payload: dict[str, Any]) -> Container:
    labels = container_payload.get("Labels") or {}
    container_names = container_payload.get("Names") or []
    created_at_unix = container_payload.get("Created")

    return Container(
        container_id=container_payload.get("Id", ""),
        container_name=container_names[0].lstrip("/") if container_names else "",
        image_name=container_payload.get("Image", ""),
        state=container_payload.get("State", ""),
        status_message=container_payload.get("Status"),
        compose_project_name=labels.get(COMPOSE_PROJECT_LABEL),
        compose_service_name=labels.get(COMPOSE_SERVICE_LABEL),
        published_ports=_published_ports_from_api(
            container_payload.get("Ports") or []
        ),
        created_at=(
            datetime.fromtimestamp(created_at_unix, tz=timezone.utc)
            if created_at_unix
            else None
        ),
    )


def _published_ports_from_api(
    port_bindings: list[dict[str, Any]],
) -> list[PublishedPort]:
    return [
        PublishedPort(
            container_port=port_binding.get("PrivatePort"),
            host_ip=port_binding.get("IP"),
            host_port=port_binding.get("PublicPort"),
            protocol=port_binding.get("Type"),
        )
        for port_binding in port_bindings
        if port_binding.get("PublicPort") is not None
    ]


if __name__ == "__main__":
    import asyncio
    import sys

    async def _main() -> None:
        socket_path = (
            sys.argv[1]
            if len(sys.argv) > 1
            else DEFAULT_DOCKER_SOCKET_PATH
        )
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10

        containers = await collect_containers(
            socket_path=socket_path,
            limit=limit,
        )

        print(f"found {len(containers)} containers\n")
        for container in containers:
            published_ports = ", ".join(
                str(published_port) for published_port in container.published_ports
            ) or "-"
            print(
                f"{container.state:<10} "
                f"{container.container_name:<24} "
                f"{container.image_name:<30} "
                f"compose={container.compose_project_name or '-':<16} "
                f"ports={published_ports}"
            )

    asyncio.run(_main())
