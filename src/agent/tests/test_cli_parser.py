"""Regression: every command must register without argparse conflicts.

A duplicate option string on one subparser raises at build time, which takes
down the whole `iw` CLI, not just the offending command.
"""
from iw_agent.cli.app import build_parser
from iw_agent.cli.registry import collect_command_specs


def test_build_parser_registers_every_command():
    parser = build_parser()
    names = {spec.name for spec in collect_command_specs()}

    assert "project" in names
    assert "nginx" in names
    # argparse would have raised above if two flags collided
    assert parser.prog == "iw"


def test_project_deploy_accepts_the_shared_interactive_flags():
    parser = build_parser()
    args = parser.parse_args(
        ["project", "deploy", "demo", "--domain", "demo.test", "--staging", "--dry-run"],
    )

    assert args.staging is True
    assert args.dry_run is True
    assert args.domain == "demo.test"
