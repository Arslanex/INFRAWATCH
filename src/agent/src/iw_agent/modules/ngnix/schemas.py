from typing import Optional

from pydantic import Field

from iw_agent.core.schemas import AgentModel


class VirtualHost(AgentModel):
    config_path: str
    server_names: list[str] = Field(default_factory=list)
    listen_ports: list[int] = Field(default_factory=list)
    upstream: Optional[str] = None
    ssl_enabled: bool = False
    cert_path: Optional[str] = None
    enabled: bool = True
    parse_ok: bool = True
    parse_error: Optional[str] = None
    raw_config: Optional[str] = None

    def __str__(self) -> str:
        names = ",".join(self.server_names) or "-"
        ports = ",".join(str(port) for port in self.listen_ports) or "-"
        cert = self.cert_path or "-"
        return f"{self.config_path} {names} ports={ports} ssl={self.ssl_enabled} cert={cert}"

    def __repr__(self) -> str:
        return (
            f"VirtualHost(config_path={self.config_path!r}, "
            f"server_names={self.server_names!r}, "
            f"listen_ports={self.listen_ports}, parse_ok={self.parse_ok})"
        )
