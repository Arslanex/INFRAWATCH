from datetime import datetime
from typing import Optional

from iw_agent.core.schemas import AgentModel


class Process(AgentModel):
    pid: int
    parent_pid: Optional[int] = None
    process_name: str
    owner: Optional[str] = None
    cpu_percent: Optional[float] = None
    memory_rss_bytes: Optional[int] = None
    started_at: Optional[datetime] = None
    command_line: Optional[str] = None
    cgroup_type: Optional[str] = None
    container_id: Optional[str] = None
    systemd_unit: Optional[str] = None
    cgroup_owner: Optional[str] = None
    process_group_id: Optional[int] = None

    def __str__(self) -> str:
        return (
            f"{self.pid} {self.process_name} "
            f"cpu={self.cpu_percent} mem={self.memory_rss_bytes}"
        )

    def __repr__(self) -> str:
        return (
            f"Process(pid={self.pid}, process_name={self.process_name!r}, "
            f"cgroup_type={self.cgroup_type!r}, "
            f"cpu_percent={self.cpu_percent}, "
            f"memory_rss_bytes={self.memory_rss_bytes})"
        )
