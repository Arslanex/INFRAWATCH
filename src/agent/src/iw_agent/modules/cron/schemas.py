from datetime import datetime
from typing import Optional

from iw_agent.core.schemas import AgentModel


class CronJob(AgentModel):
    owner: str
    cron_expression: str
    command: str
    output_log_path: Optional[str] = None

    def __str__(self) -> str:
        return f"{self.owner} {self.cron_expression} {self.command}"

    def __repr__(self) -> str:
        return (
            f"CronJob(owner={self.owner!r}, cron_expression={self.cron_expression!r}, "
            f"command={self.command!r}, output_log_path={self.output_log_path!r})"
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
