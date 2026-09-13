from datetime import datetime
from typing import Optional

from iw_agent.core.schemas import AgentModel


class Certificate(AgentModel):
    domain: str
    issuer: Optional[str] = None
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    cert_path: str
    source: str = "other"

    def __str__(self) -> str:
        return f"{self.domain} expires={self.not_after} source={self.source}"

    def __repr__(self) -> str:
        return (
            f"Certificate(domain={self.domain!r}, issuer={self.issuer!r}, "
            f"not_after={self.not_after!r}, cert_path={self.cert_path!r}, "
            f"source={self.source!r})"
        )
