from __future__ import annotations

import argparse
from argparse import _SubParsersAction

from iw_agent.cli.registry import CliCommandSpec


def add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json",
        action="store_true",
        help="print JSON output",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="disable colors and use plain text",
    )


def add_limit_flag(
    parser: argparse.ArgumentParser,
    *,
    default: int,
    help_text: str = "max rows",
) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=default,
        help=f"{help_text} (default: {default})",
    )


def add_interactive_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="interactive browser with actions",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="preview write actions without applying them",
    )
    parser.add_argument(
        "--staging",
        action="store_true",
        help="use Let's Encrypt staging environment",
    )


def add_timeout_flag(
    parser: argparse.ArgumentParser,
    *,
    default: float,
) -> None:
    parser.add_argument(
        "--timeout",
        type=float,
        default=default,
        help=f"timeout in seconds (default: {default})",
    )


def register_command(
    subparsers: _SubParsersAction,
    spec: CliCommandSpec,
) -> None:
    parser = subparsers.add_parser(
        spec.name,
        help=spec.help,
        description=spec.help,
    )
    add_json_flag(parser)
    if spec.configure is not None:
        spec.configure(parser)
    parser.set_defaults(handler=spec.handler)


def register_commands(
    subparsers: _SubParsersAction,
    specs: list[CliCommandSpec],
) -> None:
    for spec in specs:
        register_command(subparsers, spec)
