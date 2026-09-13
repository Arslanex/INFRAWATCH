from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from iw_agent.core.actions import ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.exceptions import ExecutorError


@dataclass(frozen=True)
class RegisteredAction:
    module: str
    spec: ActionSpec

    @property
    def qualified_id(self) -> str:
        return f"{self.module}.{self.spec.id}"


class ModuleExecutor(Protocol):
    module: str

    def actions(self) -> tuple[ActionSpec, ...]:
        ...

    async def run(self, request: ActionRequest, options: ExecutorOptions) -> ActionResult:
        ...


def collect_module_executors() -> list[ModuleExecutor]:
    from iw_agent.modules.cron.executor import CronExecutor
    from iw_agent.modules.docker.executor import DockerExecutor
    from iw_agent.modules.ngnix.executor import NginxExecutor
    from iw_agent.modules.processes.executor import ProcessExecutor
    from iw_agent.modules.ssl.executor import SslExecutor

    return [
        CronExecutor(),
        DockerExecutor(),
        NginxExecutor(),
        ProcessExecutor(),
        SslExecutor(),
    ]


def build_action_index(
    executors: list[ModuleExecutor] | None = None,
) -> dict[str, ModuleExecutor]:
    index: dict[str, ModuleExecutor] = {}
    for executor in executors or collect_module_executors():
        if executor.module in index:
            raise ExecutorError(f"duplicate executor module: {executor.module}")
        index[executor.module] = executor
    return index


def build_spec_index(
    executors: list[ModuleExecutor] | None = None,
) -> dict[tuple[str, str], ActionSpec]:
    specs: dict[tuple[str, str], ActionSpec] = {}
    for executor in executors or collect_module_executors():
        for spec in executor.actions():
            key = (executor.module, spec.id)
            if key in specs:
                raise ExecutorError(
                    f"duplicate action id {spec.id!r} in module {executor.module!r}",
                )
            specs[key] = spec
    return specs


def list_registered_actions(
    executors: list[ModuleExecutor] | None = None,
) -> list[RegisteredAction]:
    registered: list[RegisteredAction] = []
    for executor in executors or collect_module_executors():
        for spec in executor.actions():
            registered.append(RegisteredAction(module=executor.module, spec=spec))
    return registered
