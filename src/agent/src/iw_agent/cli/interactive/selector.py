from __future__ import annotations

import sys


def prompt_choice(
    *,
    max_value: int,
    allow_back: bool = False,
    allow_exit: bool = True,
) -> int | None:
    while True:
        raw = input("\n> ").strip().lower()

        if allow_exit and raw in {"q", "quit", "exit"}:
            return None
        if allow_back and raw in {"b", "back"}:
            return -1
        try:
            choice = int(raw)
        except ValueError:
            print("Enter a number from the list.", file=sys.stderr)
            continue
        if 1 <= choice <= max_value:
            return choice
        print(f"Enter a number between 1 and {max_value}.", file=sys.stderr)


def prompt_yes_no(message: str, *, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{message} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Enter y or n.", file=sys.stderr)
