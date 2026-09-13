"""Regression: ActionService.run takes options as a keyword-only argument.

Module executors that dispatch nested actions (project -> docker, project ->
nginx) passed it positionally, which failed only at runtime.
"""
import ast
import inspect
import pathlib

from iw_agent.core.action_service import ActionService

SRC = pathlib.Path(inspect.getfile(ActionService)).parents[1]


def _positional_service_run_calls():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "run"
                and getattr(node.func.value, "id", "") == "service"
                and len(node.args) > 1
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    return offenders


def test_options_is_keyword_only():
    params = inspect.signature(ActionService.run).parameters
    assert params["options"].kind is inspect.Parameter.KEYWORD_ONLY


def test_no_caller_passes_options_positionally():
    assert _positional_service_run_calls() == []


def test_every_registered_action_has_a_unique_qualified_id():
    actions = ActionService().list_actions()
    qualified = [f"{module}.{spec.id}" for module, spec in actions]

    assert len(qualified) == len(set(qualified))
    assert qualified  # the registry is not empty
