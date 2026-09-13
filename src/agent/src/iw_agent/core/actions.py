from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable

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
    audit_log_path: str = "logs/actions.log"


class ActionRequest(AgentModel):
    module: str
    action_id: str
    target_id: str | None = None
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
