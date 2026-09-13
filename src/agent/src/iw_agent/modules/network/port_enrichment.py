from __future__ import annotations

from iw_agent.core.psutil_helpers import normalize_ip_address
from iw_agent.modules.docker.schemas import Container, PublishedPort
from iw_agent.modules.network.schemas import ListeningPort
from iw_agent.modules.processes.cgroup import read_process_cgroup_metadata

DOCKER_PROXY_NAMES = {"docker-proxy", "docker-proxy-current"}


def owner_label_from_pid(pid: int | None, process_name: str | None = None) -> str | None:
    if pid is None:
        return None

    attribution = read_process_cgroup_metadata(pid)
    if attribution.systemd_unit:
        return f"service {attribution.systemd_unit}"
    if attribution.container_id:
        return f"docker container {attribution.container_id}"
    if attribution.cgroup_owner and attribution.cgroup_owner != process_name:
        return attribution.cgroup_owner
    return None


def build_docker_port_mapping(
    containers: list[Container],
) -> dict[tuple[str, int, str], str]:
    mapping: dict[tuple[str, int, str], str] = {}

    for container in containers:
        label = _docker_port_label(container)
        for published_port in container.published_ports:
            for host_ip in _host_ip_candidates(published_port):
                protocol = (published_port.protocol or "tcp").lower()
                if published_port.host_port is None:
                    continue
                mapping[(host_ip, published_port.host_port, protocol)] = label

    return mapping


def enrich_listening_port_owner(
    port: ListeningPort,
    docker_mapping: dict[tuple[str, int, str], str],
) -> None:
    docker_label = lookup_docker_port(docker_mapping, port)
    if docker_label:
        port.owner_label = docker_label
        return

    cgroup_label = owner_label_from_pid(port.pid, port.process_name)
    if cgroup_label:
        port.owner_label = cgroup_label
        return

    if port.process_name in DOCKER_PROXY_NAMES:
        port.owner_label = "docker published port (container unknown)"
        return

    port.owner_label = None


def lookup_docker_port(
    mapping: dict[tuple[str, int, str], str],
    port: ListeningPort,
) -> str | None:
    protocol = port.protocol.lower()
    listen_address = normalize_ip_address(port.listen_address)

    candidates = [
        (listen_address, port.port_number, protocol),
        ("any", port.port_number, protocol),
    ]
    if listen_address in {"127.0.0.1", "::1"}:
        candidates.insert(0, ("any", port.port_number, protocol))

    for key in candidates:
        if key in mapping:
            return mapping[key]

    for (host_ip, host_port, host_protocol), label in mapping.items():
        if host_port != port.port_number or host_protocol != protocol:
            continue
        if host_ip == "any" or host_ip == listen_address:
            return label

    return None


def _docker_port_label(container: Container) -> str:
    if container.compose_project_name and container.compose_service_name:
        return f"docker: {container.compose_project_name}/{container.compose_service_name}"
    if container.compose_project_name:
        return f"docker: {container.compose_project_name} ({container.container_name})"
    return f"docker: {container.container_name}"


def _host_ip_candidates(published_port: PublishedPort) -> list[str]:
    host_ip = published_port.host_ip
    if not host_ip or host_ip in {"0.0.0.0", "::"}:
        return ["any", "127.0.0.1", "0.0.0.0"]
    return [normalize_ip_address(host_ip), "any"]
