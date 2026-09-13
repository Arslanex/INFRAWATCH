from __future__ import annotations

import sys

from iw_agent.core.actions import ActionKind, ActionResult, ActionSpec
from iw_agent.core.exceptions import ActionCancelledError


def confirm_action(
    spec: ActionSpec,
    *,
    target_label: str = "",
    dry_run: bool = False,
) -> None:
    if spec.kind == ActionKind.READ:
        return

    scope = f" on {target_label}" if target_label else ""
    mode = " (dry-run)" if dry_run else ""
    print(f"\nAction: {spec.label}{scope}{mode}")
    if spec.description:
        print(f"  {spec.description}")

    if spec.kind == ActionKind.DESTRUCTIVE or spec.double_confirm:
        typed = input("Type YES to confirm: ").strip()
        if typed != "YES":
            raise ActionCancelledError("confirmation declined")
        return

    answer = input("Continue? [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        raise ActionCancelledError("confirmation declined")


def print_action_result(result: ActionResult) -> None:
    prefix = "[dry-run] " if result.dry_run else ""
    stream = sys.stdout if result.ok else sys.stderr
    print(f"{prefix}{result.message}", file=stream)
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
