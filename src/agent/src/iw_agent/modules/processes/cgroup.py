from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from iw_agent.core.exceptions import ProcessCgroupUnreadableError
from iw_agent.core.logger import logger
from iw_agent.modules.processes.schemas import Process

CGROUP_TYPE_CONTAINER = "container"
CGROUP_TYPE_SYSTEMD = "systemd"
CGROUP_TYPE_KUBERNETES = "kubernetes"
CGROUP_TYPE_USER = "user"
CGROUP_TYPE_OTHER = "other"

CONTAINER_SCOPE_PATTERN = re.compile(
    r"(?:docker|libpod|cri-containerd)-([0-9a-f]{12,64})\.scope"
)
CONTAINER_ID_PATTERN = re.compile(r"[0-9a-f]{12,64}")
KUBEPOD_SLICE_PATTERN = re.compile(
    r"kubepods(?:-[^/]+)?-pod"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.slice"
)
SESSION_SCOPE_PATTERN = re.compile(r"session-\d+\.scope")
USER_SLICE_PATTERN = re.compile(r"user-\d+\.slice")
DOCKER_SHORT_ID_LENGTH = 12


@dataclass(frozen=True)
class CgroupAttribution:
    cgroup_type: str | None = None
    container_id: str | None = None
    systemd_unit: str | None = None
    cgroup_owner: str | None = None


def enrich_process_metadata(process: Process) -> None:
    apply_cgroup_attribution(process, read_process_cgroup_metadata(process.pid))
    process.process_group_id = read_process_group_id(process.pid)


def read_process_cgroup_metadata(pid: int) -> CgroupAttribution:
    # 1. /proc/<pid>/cgroup dosyasını oku
    try:
        cgroup_text = Path(f"/proc/{pid}/cgroup").read_text()
    except (OSError, ValueError) as exc:
        logger.debug("%s", ProcessCgroupUnreadableError(f"pid={pid}: {exc}"))
        return CgroupAttribution()

    # 2. Metni parse et
    return parse_cgroup_text(cgroup_text)


def parse_cgroup_text(cgroup_text: str) -> CgroupAttribution:
    for line in cgroup_text.splitlines():
        cgroup_path = line.rpartition(":")[2]
        attribution = _resolve_cgroup_attribution(cgroup_path)
        if attribution.cgroup_type is not None:
            return attribution

    return CgroupAttribution()


def apply_cgroup_attribution(process: Process, attribution: CgroupAttribution) -> None:
    process.cgroup_type = attribution.cgroup_type
    process.container_id = attribution.container_id
    process.systemd_unit = attribution.systemd_unit
    process.cgroup_owner = attribution.cgroup_owner


def read_process_group_id(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except (OSError, AttributeError):
        return None


def _resolve_cgroup_attribution(cgroup_path: str) -> CgroupAttribution:
    segments = [segment for segment in cgroup_path.split("/") if segment]
    if not segments:
        return CgroupAttribution()

    # İçten dışa: process'e en yakın sahip geçerli
    for index in range(len(segments) - 1, -1, -1):
        segment = segments[index]

        scope_match = CONTAINER_SCOPE_PATTERN.fullmatch(segment)
        if scope_match:
            container_id = scope_match.group(1)[:DOCKER_SHORT_ID_LENGTH]
            return CgroupAttribution(
                cgroup_type=CGROUP_TYPE_CONTAINER,
                container_id=container_id,
                cgroup_owner=container_id,
            )

        if segment.endswith(".service"):
            return CgroupAttribution(
                cgroup_type=CGROUP_TYPE_SYSTEMD,
                systemd_unit=segment,
                cgroup_owner=segment,
            )

        if (
            index > 0
            and segments[index - 1] == "docker"
            and CONTAINER_ID_PATTERN.fullmatch(segment)
        ):
            container_id = segment[:DOCKER_SHORT_ID_LENGTH]
            return CgroupAttribution(
                cgroup_type=CGROUP_TYPE_CONTAINER,
                container_id=container_id,
                cgroup_owner=container_id,
            )

        kubepod_match = KUBEPOD_SLICE_PATTERN.fullmatch(segment)
        if kubepod_match:
            pod_uid = kubepod_match.group(1)
            return CgroupAttribution(
                cgroup_type=CGROUP_TYPE_KUBERNETES,
                cgroup_owner=pod_uid,
            )

        if SESSION_SCOPE_PATTERN.fullmatch(segment) or USER_SLICE_PATTERN.fullmatch(
            segment
        ):
            return CgroupAttribution(
                cgroup_type=CGROUP_TYPE_USER,
                cgroup_owner=segment,
            )

        if segment.endswith((".scope", ".slice")):
            return CgroupAttribution(
                cgroup_type=CGROUP_TYPE_OTHER,
                cgroup_owner=segment,
            )

    # Tanınmayan path: son segmenti other olarak işaretle
    return CgroupAttribution(
        cgroup_type=CGROUP_TYPE_OTHER,
        cgroup_owner=segments[-1],
    )
