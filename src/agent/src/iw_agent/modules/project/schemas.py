from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from iw_agent.core.schemas import AgentModel
from iw_agent.modules.network.schemas import PortCheckResult


class ProjectKind(str, Enum):
    DOCKER_COMPOSE = "docker-compose"
    DOCKERFILE = "dockerfile"
    STATIC = "static"
    PROXY = "proxy"
    UNKNOWN = "unknown"


class ProjectSource(AgentModel):
    type: Literal["git", "local"]
    url: Optional[str] = None
    path: Optional[str] = None
    ref: str = "main"


class ProjectProfile(AgentModel):
    kind: ProjectKind = ProjectKind.UNKNOWN
    compose_file: Optional[str] = None
    dockerfile_path: Optional[str] = None
    static_root: Optional[str] = None
    detected_ports: list[int] = []
    host_ports: list[int] = []
    suggested_backend_port: Optional[int] = None
    detected_at: Optional[datetime] = None


class ProjectDeployState(AgentModel):
    compose_project: Optional[str] = None
    domain: Optional[str] = None
    nginx_config_path: Optional[str] = None
    https_enabled: bool = False
    last_deploy_at: Optional[datetime] = None
    last_deploy_ok: bool = False
    last_message: str = ""
    containers_running: int = 0
    containers_total: int = 0


class ProjectManifest(AgentModel):
    name: str
    source: ProjectSource
    workspace_path: str
    repo_path: str
    created_at: datetime
    profile: ProjectProfile = ProjectProfile()
    deploy: ProjectDeployState = ProjectDeployState()


class DeployResult(AgentModel):
    name: str
    ok: bool
    message: str
    steps: list[str] = []
    containers_running: int = 0
    containers_total: int = 0
    port_checks: list[PortCheckResult] = []


class DetectResult(AgentModel):
    name: str
    repo_path: str
    profile: ProjectProfile
    port_checks: list[PortCheckResult] = []
    hints: list[str] = []


class ProjectSummary(AgentModel):
    name: str
    kind: ProjectKind
    source_type: str
    repo_path: str
    suggested_backend_port: Optional[int] = None
    host_ports: list[int] = []
    domain: Optional[str] = None
    deploy_ok: bool = False
    containers_running: int = 0
