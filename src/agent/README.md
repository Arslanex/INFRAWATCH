# InfraWatch Agent

Read-only collectors for server inspection: processes, network, Docker, nginx, SSL certificates, cron jobs, and device metrics.

This package is the **collector layer** of the InfraWatch agent. It gathers host data and exposes it through a CLI (`iw`) and Python APIs. Transport to core (WebSocket daemon, executors) is not included yet.

## Requirements

- Python 3.9+
- Linux or macOS (some collectors need root for full data)

## Install

**Recommended** — from the repository root (installs OS Python on Linux + all pip packages):

```bash
sudo ./setup-agent.sh --system
iw --help
```

**Manual** — if Python 3.9+ and `venv` are already available:

```bash
./setup-agent.sh
source .venv/bin/activate
iw --help
```

The setup script installs these Python packages automatically:

`psutil`, `pydantic`, `httpx`, `python-crontab`, `cryptography`

On Linux as root it also installs system packages: `python3`, `python3-venv`, build tools, `libffi`, `openssl`, `libcap`, `cron`, and (with `--system`) `nginx` and `docker.io` when available.

Without installing, run from source:

```bash
PYTHONPATH=src python -m iw_agent device
```

## CLI

Commands are flat and plain English:

| Command | Description |
|---------|-------------|
| `iw device` | Full device overview (OS, metrics, disks) |
| `iw metrics` | CPU, memory, load, network counters |
| `iw disks` | Disk usage by mount point |
| `iw ports` | Listening TCP/UDP ports |
| `iw connections` | Outbound connections (summary) |
| `iw network` | Ports + connections together |
| `iw processes` | Top processes by CPU |
| `iw containers` | Docker containers |
| `iw nginx` | Nginx virtual hosts |
| `iw nginx-config` | Advanced: `nginx -T` check + SSL cert paths |
| `iw certs` | SSL certificates on disk |
| `iw cron` | Scheduled cron jobs |
| `iw cron-history` | Recent cron run results |

```bash
iw                      # interactive menu
iw device
iw ports --json
iw processes --limit 20
iw containers --socket /var/run/docker.sock
iw certs --certbot-dir /etc/letsencrypt/live
iw cron-history --log-dir logs/cron
```

Add `--json` on any command for machine-readable output.

## Collectors (Python API)

Each module lives under `src/iw_agent/modules/` with `schemas.py` and `collector.py`:

```python
import asyncio
from iw_agent.modules.device.collector import collect_device_snapshot
from iw_agent.modules.network.collector import collect_network_snapshot
from iw_agent.modules.processes.collector import collect_processes

async def main():
    device = await collect_device_snapshot()
    network = await collect_network_snapshot()
    processes = await collect_processes(limit=10)
    print(device.to_dict())
    print(len(network.listening_ports), "ports")
    print(len(processes), "processes")

asyncio.run(main())
```

All models extend `AgentModel` and support `.to_dict()` / `.model_dump()`.

## Project layout

```
src/iw_agent/
├── cli/                 # iw command, menu, output formatting
├── core/                # logger, exceptions, psutil helpers, subprocess runner
└── modules/
    ├── device/          # OS, CPU/RAM/load, disks
    ├── network/         # listening ports + outbound connections
    ├── processes/       # process list + cgroup attribution
    ├── docker/          # Docker Engine API (unix socket)
    ├── ngnix/           # nginx -T virtual host parser
    ├── ssl/             # X.509 certificates (certbot + nginx paths)
    └── cron/            # crontab jobs + execution history
```

## Permissions

| Collector | Notes |
|-----------|--------|
| `network`, `processes` | Often need root for `psutil.net_connections` / full process list |
| `docker` | Requires access to `/var/run/docker.sock` |
| `nginx`, `ssl` | Needs read access to nginx config and certificate files |
| `cron` | User crontabs readable by owner; system crontabs may need root |
| `device` | Usually works without root; some mount points may be skipped |

On failure, privileged collectors raise typed errors (e.g. `NetworkAccessDeniedError`). Optional services (Docker, nginx) return empty results instead of crashing.

## Development

```bash
pip install .
iw metrics
python -m iw_agent.modules.device.collector
```

Logs: debug lines are hidden in CLI mode; errors still go to `logs/error.log` when written.

## License

Part of the InfraWatch project.
