from __future__ import annotations

import argparse
import sys

from iw_agent.cli.output import clear_screen, print_banner
from iw_agent.cli.registry import collect_command_specs
from iw_agent.cli.runner import run_async
from iw_agent.core.paths import cron_log_dir

_MANAGE_COMMANDS = frozenset({"nginx", "cron", "containers", "processes", "certs", "project"})


def run_menu() -> int:
    return run_async(_interactive_menu)


async def _interactive_menu() -> None:
    specs = collect_command_specs()

    while True:
        clear_screen()
        print_banner()
        print("What do you want to check?\n")
        for index, spec in enumerate(specs, start=1):
            print(f"  {index:2}. {spec.name:<16} {spec.help}")
        print("   0. exit")

        choice = _read_choice(len(specs))
        if choice == 0:
            print("bye")
            return

        selected = specs[choice - 1]
        args = _default_args()
        if selected.name in _MANAGE_COMMANDS:
            args = _command_menu_args(selected.name, args)
            if args is None:
                continue
        await selected.handler(args)


def _command_menu_args(name: str, args: argparse.Namespace) -> argparse.Namespace | None:
    labels = {
        "nginx": ("view sites", "manage sites (certbot, enable, reload)"),
        "cron": ("view jobs", "manage jobs (run, enable, disable)"),
        "containers": ("view containers", "manage containers (start, stop, restart)"),
        "processes": ("view processes", "manage processes (details, kill)"),
        "certs": ("view certificates", "manage certificates (renew, obtain)"),
        "project": ("view projects", "manage projects (add, deploy, stop)"),
    }
    view_label, manage_label = labels[name]
    print(f"\n{name}:")
    print(f"  1. {view_label} (read-only)")
    print(f"  2. {manage_label}")
    while True:
        raw = input("\n> ").strip()
        if raw in {"q", "quit", "exit", "0"}:
            return None
        if raw in {"", "1"}:
            return args
        if raw == "2":
            args.interactive = True
            if name == "containers":
                args.limit = 200
            return args
        print("Enter 1, 2, or q.", file=sys.stderr)


def _read_choice(max_value: int) -> int:
    while True:
        raw = input("\n> ").strip()
        if raw in {"q", "quit", "exit"}:
            return 0
        try:
            choice = int(raw)
        except ValueError:
            print("Enter a number from the list.", file=sys.stderr)
            continue
        if 0 <= choice <= max_value:
            return choice
        print(f"Enter a number between 0 and {max_value}.", file=sys.stderr)


def _default_args() -> argparse.Namespace:
    return argparse.Namespace(
        json=False,
        plain=False,
        interactive=False,
        dry_run=False,
        staging=False,
        limit=10,
        outbound_limit=20,
        timeout=30.0,
        socket_path="/var/run/docker.sock",
        nginx_binary="nginx",
        certbot_live_dir="/etc/letsencrypt/live",
        nginx_paths=[],
        log_directory=str(cron_log_dir()),
        tail=50,
        show_stdout=False,
        workspace=None,
    )
