from __future__ import annotations

import sys

from iw_agent.cli.menu import run_menu
from iw_agent.cli.parser import register_commands
from iw_agent.cli.registry import collect_command_specs
from iw_agent.cli.runner import run_async


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="iw",
        description="InfraWatch agent — read-only server inspection",
        epilog="examples: iw device · iw ports · iw containers · iw certs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--menu",
        action="store_true",
        help="open interactive menu",
    )

    subparsers = parser.add_subparsers(dest="command")
    register_commands(subparsers, collect_command_specs())
    return parser


def main(argv: list[str] | None = None) -> None:
    from iw_agent.core.logger import configure_cli_logging

    configure_cli_logging()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.menu or args.command is None:
        raise SystemExit(run_menu())

    if not hasattr(args, "handler"):
        parser.print_help()
        raise SystemExit(1)

    exit_code = run_async(lambda: args.handler(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main(sys.argv[1:])
