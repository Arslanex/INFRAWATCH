from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from iw_agent.core.paths import audit_log_path
from iw_agent.core.schemas import AgentModel


class ActionKind(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


@dataclass(frozen=True)
class ActionSpec:
    id: str
    label: str
    kind: ActionKind
    requires_root: bool = False
    description: str = ""
    double_confirm: bool = False


@dataclass
class ExecutorOptions:
    dry_run: bool = False
    skip_confirm: bool = False
    # resolved per instance so an env override or running as root is honoured
    audit_log_path: str = field(default_factory=lambda: str(audit_log_path()))


class ActionRequest(AgentModel):
    module: str
    action_id: str
    target_id: Optional[str] = None
    params: dict[str, Any] = {}


class ActionResult(AgentModel):
    ok: bool
    module: str
    action_id: str
    message: str
    dry_run: bool = False
    stdout: str = ""
    stderr: str = ""


ActionHandler = Callable[[ActionRequest, ExecutorOptions], Awaitable[ActionResult]]
