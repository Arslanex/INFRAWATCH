# InfraWatch Agent

Server inspection and local operations: processes, network, Docker, nginx, SSL certificates, cron jobs, device metrics, and **project register/publish**.

Collectors are read-only; module **executors** handle writes (nginx reload, certbot, docker compose, cron edits, project deploy). The CLI (`iw`) routes actions through `ActionService` with confirmation prompts and an audit log.

## Requirements

- Python 3.9+
- Linux or macOS (some collectors need root for full data)

## Install

**Recommended** — from the repository root:

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

The setup script installs: `psutil`, `pydantic`, `httpx`, `python-crontab`, `cryptography`

On Linux as root it can also install: `python3`, `python3-venv`, build tools, `libffi`, `openssl`, `libcap`, `cron`, and (with `--system`) `nginx`, `docker.io`, and certbot when available.

Without installing, run from source:

```bash
PYTHONPATH=src python -m iw_agent device
```

## CLI

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
| `iw project` | Registered projects (list, register, publish, deploy, stop) |

```bash
iw                      # interactive menu
iw device
iw ports --json
iw processes --limit 20
iw containers --socket /var/run/docker.sock
iw certs --certbot-dir /etc/letsencrypt/live
iw cron-history --log-dir logs/cron
iw project register /path/to/clone --name myapp
sudo iw project publish myapp --domain app.example.com --backend-port 8000
```

Add `--json` on any command for machine-readable output.

**Full reference:** [docs/AGENT-COMMANDS.md](../../docs/AGENT-COMMANDS.md)

## Interactive managers (`-i`)

Use `-i` for full-screen card pickers and action menus (confirm + audit log):

| Command | What you get |
|---------|----------------|
| `sudo iw nginx -i` | Site picker → structural config editor; `o` enable/disable |
| `sudo iw cron -i` | Job picker → run, enable/disable, history |
| `iw containers -i` | Container picker → start/stop/restart, logs |
| `sudo iw processes -i` | Process picker → details, kill |
| `sudo iw certs -i` | Certificate picker → renew, obtain new |
| `iw project -i` | Project picker → register, publish/deploy, nginx editor |

Add `--dry-run` to preview write actions without applying them.

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
├── cli/                 # iw command, TUI card pickers, output
├── core/                # actions, audit log, paths, subprocess runner
└── modules/
    ├── device/
    ├── network/
    ├── processes/
    ├── docker/
    ├── nginx/           # collector, executor, structural editor
    ├── ssl/
    ├── cron/
    └── project/         # register, detect, publish/deploy, manifest
```

## Permissions

| Area | Notes |
|------|--------|
| `network`, `processes` | Often need root for full connection/process lists |
| `docker` | Requires access to `/var/run/docker.sock` |
| `nginx`, `ssl` | Read configs/certs; writes need root |
| `cron` | User crontabs editable by owner; system crontabs may need root |
| `project` | Deploy/publish nginx + compose usually needs root |
| `device` | Usually works without root |

Write actions are logged to `logs/actions.log`. On failure, collectors raise typed errors; optional services (Docker, nginx) return empty results instead of crashing.

## Development

```bash
pip install -e .
pytest
iw metrics
```

Logs: debug lines are hidden in CLI mode; errors still go to `logs/error.log` when written.

## License

Part of the InfraWatch project.
