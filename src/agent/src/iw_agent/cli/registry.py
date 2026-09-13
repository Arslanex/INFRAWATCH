from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass(frozen=True)
class CliCommandSpec:
    name: str
    help: str
    handler: Callable[..., Awaitable[None]]
    configure: Callable | None = None


def collect_command_specs() -> list[CliCommandSpec]:
    from iw_agent.modules.cron.commands import COMMAND_SPECS as cron_specs
    from iw_agent.modules.device.commands import COMMAND_SPECS as device_specs
    from iw_agent.modules.docker.commands import COMMAND_SPECS as docker_specs
    from iw_agent.modules.network.commands import COMMAND_SPECS as network_specs
    from iw_agent.modules.ngnix.commands import COMMAND_SPECS as ngnix_specs
    from iw_agent.modules.processes.commands import COMMAND_SPECS as process_specs
    from iw_agent.modules.ssl.commands import COMMAND_SPECS as ssl_specs

    specs: list[CliCommandSpec] = []
    for group in (
        device_specs,
        network_specs,
        process_specs,
        docker_specs,
        ngnix_specs,
        ssl_specs,
        cron_specs,
    ):
        specs.extend(group)
    return specs
