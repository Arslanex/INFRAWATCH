from __future__ import annotations

from iw_agent.core.action_registry import (
    ModuleExecutor,
    build_action_index,
    build_spec_index,
    collect_module_executors,
    list_registered_actions,
)
from iw_agent.core.actions import ActionRequest, ActionResult, ActionSpec, ExecutorOptions
from iw_agent.core.exceptions import ExecutorError
from iw_agent.core.executor_runtime import run_action


class ActionService:
    """Transport-agnostic entry point for module executors (CLI, HTTP, WebSocket)."""

    def __init__(self, executors: list[ModuleExecutor] | None = None) -> None:
        executor_list = executors or collect_module_executors()
        self._executors = build_action_index(executor_list)
        self._specs = build_spec_index(executor_list)

    def list_actions(self, module: str | None = None) -> list[tuple[str, ActionSpec]]:
        actions = list_registered_actions(list(self._executors.values()))
        if module is not None:
            actions = [entry for entry in actions if entry.module == module]
        return [(entry.module, entry.spec) for entry in actions]

    def get_spec(self, module: str, action_id: str) -> ActionSpec:
        spec = self._specs.get((module, action_id))
        if spec is None:
            raise ExecutorError(f"unknown action {module}.{action_id}")
        return spec

    def get_executor(self, module: str) -> ModuleExecutor:
        executor = self._executors.get(module)
        if executor is None:
            raise ExecutorError(f"unknown module {module!r}")
        return executor

    async def run(
        self,
        request: ActionRequest,
        *,
        options: ExecutorOptions | None = None,
        target_label: str = "",
    ) -> ActionResult:
        spec = self.get_spec(request.module, request.action_id)
        executor = self.get_executor(request.module)

        async def _handler(action_request: ActionRequest, opts: ExecutorOptions) -> ActionResult:
            return await executor.run(action_request, opts)

        return await run_action(
            spec,
            request,
            _handler,
            options=options,
            target_label=target_label,
        )


_default_service: ActionService | None = None


def get_action_service() -> ActionService:
    global _default_service
    if _default_service is None:
        _default_service = ActionService()
    return _default_service
