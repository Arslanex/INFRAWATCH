from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from iw_agent.cli.output import prepare_command_view


@dataclass(frozen=True)
class CliCommandSpec:
    name: str
    help: str
    handler: Callable[..., Awaitable[None]]
    configure: Callable | None = None


def _wrap_command_handler(
    handler: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[None]]:
    async def wrapped(args) -> None:
        if not getattr(args, "json", False) and not getattr(args, "interactive", False):
            prepare_command_view(plain=getattr(args, "plain", False))
        await handler(args)

    return wrapped


def collect_command_specs() -> list[CliCommandSpec]:
    from iw_agent.modules.cron.commands import COMMAND_SPECS as cron_specs
    from iw_agent.modules.device.commands import COMMAND_SPECS as device_specs
    from iw_agent.modules.docker.commands import COMMAND_SPECS as docker_specs
    from iw_agent.modules.network.commands import COMMAND_SPECS as network_specs
    from iw_agent.modules.nginx.commands import COMMAND_SPECS as nginx_specs
    from iw_agent.modules.processes.commands import COMMAND_SPECS as process_specs
    from iw_agent.modules.project.commands import COMMAND_SPECS as project_specs
    from iw_agent.modules.ssl.commands import COMMAND_SPECS as ssl_specs

    specs: list[CliCommandSpec] = []
    for group in (
        device_specs,
        network_specs,
        process_specs,
        docker_specs,
        nginx_specs,
        ssl_specs,
        cron_specs,
        project_specs,
    ):
        specs.extend(
            CliCommandSpec(
                name=spec.name,
                help=spec.help,
                handler=_wrap_command_handler(spec.handler),
                configure=spec.configure,
            )
            for spec in group
        )
    return specs
