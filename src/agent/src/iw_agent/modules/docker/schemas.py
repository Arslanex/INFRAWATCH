from datetime import datetime
from typing import Optional

from pydantic import Field

from iw_agent.core.schemas import AgentModel


class PublishedPort(AgentModel):
    container_port: Optional[int] = None
    host_ip: Optional[str] = None
    host_port: Optional[int] = None
    protocol: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"{self.host_ip}:{self.host_port}->{self.container_port}/"
            f"{self.protocol or '-'}"
        )


class Container(AgentModel):
    container_id: str
    container_name: str
    image_name: str
    state: str
    status_message: Optional[str] = None
    compose_project_name: Optional[str] = None
    compose_service_name: Optional[str] = None
    published_ports: list[PublishedPort] = Field(default_factory=list)
    created_at: Optional[datetime] = None

    def __str__(self) -> str:
        return f"{self.container_name} {self.state} {self.image_name}"

    def __repr__(self) -> str:
        return (
            f"Container(container_id={self.container_id!r}, "
            f"container_name={self.container_name!r}, state={self.state!r}, "
            f"image_name={self.image_name!r})"
        )
