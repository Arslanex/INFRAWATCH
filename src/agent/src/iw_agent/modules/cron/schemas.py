import hashlib
from datetime import datetime
from typing import Literal, Optional

from iw_agent.core.schemas import AgentModel


def compute_job_id(owner: str, cron_expression: str, command: str) -> str:
    payload = f"{owner}\0{cron_expression}\0{command}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class CronJob(AgentModel):
    job_id: str
    owner: str
    cron_expression: str
    command: str
    enabled: bool = True
    writable: bool = False
    source: Literal["user", "system"] = "user"
    output_log_path: Optional[str] = None

    def __str__(self) -> str:
        state = "on" if self.enabled else "off"
        return f"{self.owner} [{state}] {self.cron_expression} {self.command}"

    def __repr__(self) -> str:
        return (
            f"CronJob(job_id={self.job_id!r}, owner={self.owner!r}, "
            f"cron_expression={self.cron_expression!r}, command={self.command!r}, "
            f"enabled={self.enabled!r}, writable={self.writable!r}, "
            f"source={self.source!r}, output_log_path={self.output_log_path!r})"
        )


class CronJobExecution(AgentModel):
    job_log_path: str
    started_at: datetime
    exit_code: int

    def __str__(self) -> str:
        return (
            f"{self.job_log_path} {self.started_at.isoformat()} "
            f"exit={self.exit_code}"
        )

    def __repr__(self) -> str:
        return (
            f"CronJobExecution(job_log_path={self.job_log_path!r}, "
            f"started_at={self.started_at!r}, exit_code={self.exit_code})"
        )
