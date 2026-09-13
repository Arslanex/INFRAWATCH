from datetime import datetime
from typing import Optional

from pydantic import Field

from iw_agent.core.schemas import AgentModel


class DeviceSystem(AgentModel):
    hostname: str
    operating_system: str
    os_release: Optional[str] = None
    os_version: Optional[str] = None
    machine: Optional[str] = None
    boot_time: Optional[datetime] = None

    def __repr__(self) -> str:
        return (
            f"DeviceSystem(hostname={self.hostname!r}, "
            f"operating_system={self.operating_system!r}, "
            f"os_release={self.os_release!r})"
        )


class DeviceMetrics(AgentModel):
    cpu_percent: Optional[float] = None
    cpu_count_logical: Optional[int] = None
    cpu_count_physical: Optional[int] = None
    memory_used_bytes: Optional[int] = None
    memory_total_bytes: Optional[int] = None
    load_1: Optional[float] = None
    load_5: Optional[float] = None
    load_15: Optional[float] = None
    net_rx_bytes: Optional[int] = None
    net_tx_bytes: Optional[int] = None

    def __repr__(self) -> str:
        return (
            f"DeviceMetrics(cpu_percent={self.cpu_percent}, "
            f"memory_used_bytes={self.memory_used_bytes}, "
            f"memory_total_bytes={self.memory_total_bytes})"
        )


class DiskVolume(AgentModel):
    mount_point: str
    device: str
    filesystem: Optional[str] = None
    used_bytes: int
    total_bytes: int

    def __str__(self) -> str:
        return f"{self.mount_point} {self.device} {self.used_bytes}/{self.total_bytes}"

    def __repr__(self) -> str:
        return (
            f"DiskVolume(mount_point={self.mount_point!r}, device={self.device!r}, "
            f"used_bytes={self.used_bytes}, total_bytes={self.total_bytes})"
        )


class DeviceSnapshot(AgentModel):
    system: DeviceSystem
    metrics: DeviceMetrics
    disks: list[DiskVolume] = Field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"DeviceSnapshot(hostname={self.system.hostname!r}, "
            f"disks={len(self.disks)})"
        )
