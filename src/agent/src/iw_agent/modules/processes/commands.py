from __future__ import annotations

import argparse
import psutil

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import pause, run_action_in_hub
from iw_agent.cli.interactive.context import PageContext
from iw_agent.cli.interactive.hub import pick_or_fallback, run_action_hub
from iw_agent.cli.interactive.selector import prompt_choice, prompt_yes_no
from iw_agent.cli.output import (
    BLUE,
    DIM,
    GREEN,
    RED,
    YELLOW,
    _c,
    _reset,
    emit_models,
    format_field,
    format_fields,
    format_memory_meter,
    format_meter,
    format_optional,
    format_percent,
    print_empty,
    print_info_box,
    print_insight,
    print_menu_item,
    print_page_divider,
    print_page_summary,
    print_report,
    print_status_box,
    prepare_command_view,
    process_load_details,
    status_badge,
)
from iw_agent.cli.parser import add_interactive_flags, add_limit_flag
from iw_agent.cli.registry import CliCommandSpec
from iw_agent.core.actions import ActionRequest, ActionResult, ExecutorOptions
from iw_agent.modules.processes.collector import collect_processes
from iw_agent.modules.processes.schemas import Process


async def run_processes(args: argparse.Namespace) -> None:
    if getattr(args, "interactive", False):
        await run_processes_interactive(args)
        return

    processes = await collect_processes(args.limit)
    emit_models(processes, json_output=args.json, plain=args.plain, render=_render_processes)


def _processes_summary(processes: list[Process]) -> str:
    top = processes[0]
    total_cpu = sum(process.cpu_percent or 0.0 for process in processes)
    return (
        f"Top {len(processes)} programs use {total_cpu:.1f}% CPU combined. "
        f"Busiest: {top.process_name} ({format_percent(top.cpu_percent)})."
    )


def _owner_label(process: Process) -> str:
    if process.cgroup_type == "container" and process.container_id:
        return f"docker container {process.container_id}"
    if process.systemd_unit:
        return f"service {process.systemd_unit}"
    if process.owner:
        return f"user {process.owner}"
    return format_optional(process.cgroup_owner, fallback="this server")


def _status_legend() -> str:
    parts = [
        status_badge("IDLE", "ok"),
        status_badge("WORKING", "work"),
        status_badge("WAITING", "work"),
        status_badge("HOT", "warn"),
        status_badge("BUSY", "bad"),
        status_badge("STOPPED", "off"),
        status_badge("ZOMBIE", "bad"),
    ]
    return " · ".join(parts)


def _render_process_card(process: Process, rank: int, system_ram_total: int) -> None:
    load_badge, tone = process_load_details(
        process.cpu_percent,
        process_status=process.status,
    )
    badge = f"#{rank} {load_badge}"

    lines = [
        format_meter("CPU", process.cpu_percent or 0.0),
        format_memory_meter(process.memory_rss_bytes, system_ram_total),
        format_field("State", format_optional(process.status, fallback="unknown")),
        format_field("Runs as", _owner_label(process)),
        format_field("PID", str(process.pid)),
    ]

    if process.command_line:
        command = process.command_line
        if len(command) > 72:
            command = f"{command[:69]}..."
        lines.append(format_field("Command", command))

    print_status_box(
        badge=badge,
        title=process.process_name,
        lines=lines,
        tone=tone,
    )


def _render_processes(processes: list[Process]) -> None:
    print_report(
        "Running programs",
        "The busiest programs on this server, sorted by CPU usage.",
    )
    if not processes:
        print_empty(
            "no processes listed",
            "The agent could not read the process list.",
            "try: sudo iw processes",
        )
        return

    print_insight(_processes_summary(processes))
    print_info_box(
        title="How to read",
        hint="status colors",
        lines=format_fields(
            [
                ("CPU / RAM", "bars show real usage on this server"),
                ("State", "raw psutil status (running, sleeping, zombie, …)"),
                (
                    "Colors",
                    f"{_c(GREEN)}idle{_reset()} · {_c(BLUE)}working/waiting{_reset()} · "
                    f"{_c(YELLOW)}hot{_reset()} · {_c(RED)}busy/dead{_reset()} · "
                    f"{_c(DIM)}stopped{_reset()}",
                ),
            ]
        )
        + [_status_legend()],
    )

    system_ram_total = psutil.virtual_memory().total
    for rank, process in enumerate(processes, start=1):
        _render_process_card(process, rank, system_ram_total)


def _configure(parser: argparse.ArgumentParser) -> None:
    add_interactive_flags(parser)
    add_limit_flag(parser, default=10, help_text="max processes")


def _process_list_hint(process: Process) -> str:
    cpu = format_percent(process.cpu_percent)
    parts = [cpu, _owner_label(process)]
    if process.status:
        parts.append(process.status)
    return " · ".join(parts)


def _process_params(process: Process) -> dict:
    return {"pid": process.pid}


async def _refresh_processes(context: PageContext) -> None:
    context.data["processes"] = await collect_processes(context.args.limit)


async def _run_process_action(
    context: PageContext,
    process: Process,
    action_id: str,
    *,
    params: dict | None = None,
) -> ActionResult | None:
    request = ActionRequest(
        module="processes",
        action_id=action_id,
        target_id=str(process.pid),
        params=params or _process_params(process),
    )
    label = f"{process.process_name} (pid {process.pid})"
    return await run_action_in_hub(
        request,
        options=context.data["options"],
        target_label=label,
    )


async def _interactive_pick_process(
    args: argparse.Namespace,
    processes: list[Process],
):
    from iw_agent.modules.processes.process_picker import pick_process

    summary = (
        _processes_summary(processes)
        if processes
        else "No processes could be read. Try sudo iw processes -i."
    )
    return await pick_or_fallback(
        lambda: pick_process(
            processes,
            summary=summary,
            dry_run=getattr(args, "dry_run", False),
        ),
        lambda: _interactive_pick_process_fallback(processes),
    )


async def _interactive_pick_process_fallback(
    processes: list[Process],
) -> Process | None:
    from iw_agent.cli.output import clear_screen, print_page_header

    clear_screen()
    print_page_header("Running programs", "processes")
    print_page_divider()
    print_page_summary(_processes_summary(processes))
    for index, process in enumerate(processes, start=1):
        print_menu_item(
            index,
            f"{process.process_name} (pid {process.pid})",
            _process_list_hint(process),
        )
    choice = prompt_choice(max_value=len(processes), allow_back=False, allow_exit=True)
    if choice is None:
        return None
    return processes[choice - 1]


async def _perform_process_action(
    context: PageContext,
    process: Process,
    action_id: str,
) -> Process | None:
    """Run one action. Returns ``None`` when the hub should drop back to the list."""
    params = _process_params(process)
    if action_id == "kill_process":
        if prompt_yes_no("\nSend SIGKILL if SIGTERM fails?", default=False):
            params["signal"] = "KILL"

    result = await _run_process_action(
        context,
        process,
        action_id,
        params=params,
    )
    if result is None:
        pause()
        return process

    print()
    if action_id == "view_details":
        print(result.message)
    else:
        print_action_result(result)
    pause()

    # A killed process is gone — there is nothing left to manage.
    if result.ok and action_id == "kill_process":
        await _refresh_processes(context)
        return None
    return process


async def _interactive_process_hub(context: PageContext, process: Process) -> bool:
    from iw_agent.modules.processes.action_picker import pick_process_action

    return await run_action_hub(
        process,
        pick=lambda target: pick_process_action(
            target,
            dry_run=context.data["options"].dry_run,
        ),
        perform=lambda target, action: _perform_process_action(
            context,
            target,
            action.action_id,
        ),
    )


async def run_processes_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"processes": [], "options": options},
    )
    await _refresh_processes(context)

    if not context.data["processes"]:
        print_page_divider()
        print_page_summary("No processes could be read. Try sudo iw processes -i.")
        pause()
        return

    while True:
        await _refresh_processes(context)
        processes = context.data["processes"]
        picked = await _interactive_pick_process(args, processes)
        if picked.quit_session:
            break
        if picked.value is None:
            continue
        if await _interactive_process_hub(context, picked.value):
            break


COMMAND_SPECS = [
    CliCommandSpec("processes", "top processes by cpu", run_processes, _configure),
]
