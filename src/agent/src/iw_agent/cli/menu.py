from __future__ import annotations

import argparse
import sys

from iw_agent.cli.output import clear_screen, print_banner
from iw_agent.cli.registry import collect_command_specs
from iw_agent.cli.runner import run_async


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
        await selected.handler(_default_args())


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
        limit=10,
        outbound_limit=20,
        timeout=5.0,
        socket_path="/var/run/docker.sock",
        nginx_binary="nginx",
        certbot_live_dir="/etc/letsencrypt/live",
        nginx_paths=[],
        log_directory="logs/cron",
        tail=50,
        show_stdout=False,
    )
