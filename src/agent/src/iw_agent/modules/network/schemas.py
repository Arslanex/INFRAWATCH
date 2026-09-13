from typing import Optional

from iw_agent.core.schemas import AgentModel


class ListeningPort(AgentModel):
    protocol: str
    port_number: int
    listen_address: str
    pid: Optional[int] = None
    process_name: Optional[str] = None
    owner_label: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"{self.protocol} {self.port_number} {self.listen_address} "
            f"{self.pid} {self.process_name}"
        )

    def __repr__(self) -> str:
        return (
            f"ListeningPort(protocol={self.protocol}, "
            f"port_number={self.port_number}, "
            f"listen_address={self.listen_address!r}, "
            f"pid={self.pid}, process_name={self.process_name!r})"
        )


class OutboundConnection(AgentModel):
    pid: Optional[int] = None
    process_name: Optional[str] = None
    remote_address: str
    remote_port: int
    connection_count: int

    def __str__(self) -> str:
        return (
            f"pid={self.pid} {self.process_name or '-'} "
            f"{self.remote_address}:{self.remote_port} "
            f"count={self.connection_count}"
        )

    def __repr__(self) -> str:
        return (
            f"OutboundConnection(pid={self.pid}, "
            f"process_name={self.process_name!r}, "
            f"remote_address={self.remote_address!r}, "
            f"remote_port={self.remote_port}, "
            f"connection_count={self.connection_count})"
        )


class NetworkSnapshot(AgentModel):
    listening_ports: list[ListeningPort]
    outbound_connections: list[OutboundConnection]

    def __repr__(self) -> str:
        return (
            f"NetworkSnapshot(listening_ports={len(self.listening_ports)}, "
            f"outbound_connections={len(self.outbound_connections)})"
        )


class PortCheckResult(AgentModel):
    port: int
    available: bool
    listener: Optional[str] = None
    owner_label: Optional[str] = None
    note: str = ""
