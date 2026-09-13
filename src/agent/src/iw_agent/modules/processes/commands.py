from __future__ import annotations

import argparse
from dataclasses import dataclass

import psutil

from iw_agent.cli.action_prompts import print_action_result
from iw_agent.cli.action_runner import run_action_with_prompts
from iw_agent.cli.interactive.navigator import Navigator, Page, PageContext, PageResult
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
from iw_agent.core.exceptions import ActionCancelledError, ActionDeniedError
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


@dataclass(frozen=True)
class _HubEntry:
    label: str
    hint: str = ""
    action_id: str = ""


def _process_params(process: Process) -> dict:
    return {"pid": process.pid}


def _process_hub_menu(process: Process) -> list[_HubEntry]:
    return [
        _HubEntry("View details", "CPU, memory, cgroup, command", "view_details"),
        _HubEntry("Kill process", "send SIGTERM (type YES to confirm)", "kill_process"),
    ]


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
    try:
        return await run_action_with_prompts(
            request,
            options=context.data["options"],
            target_label=label,
        )
    except ActionCancelledError:
        print("\nCancelled.")
        return None
    except ActionDeniedError as exc:
        print(f"\n{exc.message}")
        return None


async def run_processes_interactive(args: argparse.Namespace) -> None:
    prepare_command_view(plain=args.plain)
    processes = await collect_processes(args.limit)
    options = ExecutorOptions(dry_run=getattr(args, "dry_run", False))
    context = PageContext(
        args=args,
        data={"processes": processes, "options": options},
    )
    await Navigator(context).run(_InteractiveProcessListPage())


class _InteractiveProcessListPage(Page):
    @property
    def title(self) -> str:
        return "Processes"

    @property
    def subtitle(self) -> str:
        return "processes"

    def render(self, context: PageContext) -> None:
        processes: list[Process] = context.data["processes"]
        print_page_divider()
        if not processes:
            print_page_summary("No processes could be read. Try sudo iw processes -i.")
            return

        for index, process in enumerate(processes, start=1):
            print_menu_item(
                index,
                f"{process.process_name} (pid {process.pid})",
                _process_list_hint(process),
            )

    async def handle(self, context: PageContext) -> PageResult | Page:
        processes: list[Process] = context.data["processes"]
        if not processes:
            return PageResult.EXIT

        choice = prompt_choice(max_value=len(processes), allow_back=False, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        return _InteractiveProcessDetailPage(processes[choice - 1])


class _InteractiveProcessDetailPage(Page):
    def __init__(self, process: Process) -> None:
        self._process = process
        self._menu = _process_hub_menu(process)

    @property
    def title(self) -> str:
        return f"{self._process.process_name} (pid {self._process.pid})"

    @property
    def subtitle(self) -> str:
        return "processes"

    def render(self, context: PageContext) -> None:
        system_ram_total = psutil.virtual_memory().total
        print_page_divider()
        print_page_summary(_process_list_hint(self._process))
        print(f"   {format_meter('CPU', self._process.cpu_percent or 0.0)}")
        print(f"   {format_memory_meter(self._process.memory_rss_bytes, system_ram_total)}")
        if self._process.command_line:
            command = self._process.command_line
            if len(command) > 72:
                command = f"{command[:69]}..."
            print(f"   cmd: {command}")
        print_page_divider()
        for index, entry in enumerate(self._menu, start=1):
            print_menu_item(index, entry.label, entry.hint)

    async def handle(self, context: PageContext) -> PageResult | Page:
        choice = prompt_choice(max_value=len(self._menu), allow_back=True, allow_exit=True)
        if choice is None:
            return PageResult.EXIT
        if choice == -1:
            return PageResult.BACK

        entry = self._menu[choice - 1]
        params = _process_params(self._process)

        if entry.action_id == "kill_process":
            if prompt_yes_no("\nSend SIGKILL if SIGTERM fails?", default=False):
                params["signal"] = "KILL"

        result = await _run_process_action(
            context,
            self._process,
            entry.action_id,
            params=params,
        )
        if result is None:
            input("\nPress Enter to continue...")
            return PageResult.STAY

        print()
        if entry.action_id == "view_details":
            print(result.message)
        else:
            print_action_result(result)
        input("\nPress Enter to continue...")

        if result.ok and entry.action_id == "kill_process":
            await _refresh_processes(context)
            return PageResult.BACK
        return PageResult.STAY


COMMAND_SPECS = [
    CliCommandSpec("processes", "top processes by cpu", run_processes, _configure),
]
