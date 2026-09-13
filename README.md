# InfraWatch

InfraWatch monitors your servers from the inside out: a lightweight agent reads what each host is doing, a central service stores and alerts on that data, and a dashboard lets you inspect and operate your infrastructure from one place.

This repository is under active development. **The agent (collectors + CLI + local executors) is implemented today.** Core and dashboard are planned.

## Architecture (planned)

```
┌─────────────┐     WebSocket      ┌─────────────┐     HTTP/API    ┌─────────────┐
│   Agent     │ ─────────────────► │    Core     │ ◄────────────── │  Dashboard  │
│  (on host)  │      snapshots     │   (server)  │                 │  (console)  │
└─────────────┘                    └─────────────┘                 └─────────────┘
```

| Component | Path | Status |
|-----------|------|--------|
| **Agent** | [`src/agent/`](src/agent/) | **In progress** — collectors, CLI, executors |
| Core (server) | `src/server/` | Planned |
| Dashboard (console) | `src/console/` | Planned |

The agent runs on each monitored machine. It collects snapshots (processes, ports, Docker, nginx, certificates, cron, device metrics) and applies local changes through audited executors (nginx reload, certbot, docker compose, cron edits, project deploy/publish). Core and the dashboard will sit on top of that transport layer.

## What works today

- **Collectors** — read-only module APIs under `src/agent/src/iw_agent/modules/`
- **CLI (`iw`)** — inspect the host and run interactive managers with `-i`
- **Executors** — nginx (structural editor + site enable/disable), SSL/certbot, Docker, cron, processes, **project register/publish**
- **Interactive TUI** — full-screen card pickers for nginx, cron, containers, processes, certs, and projects

Not yet in this repo: long-running daemon, WebSocket transport to core, remote command queue from a central server.

## Quick start (agent)

From the repository root on a **fresh Linux server**:

```bash
sudo ./setup-agent.sh --system
iw device
iw ports
sudo iw nginx -i
```

The setup script installs Python, pip dependencies, optional nginx/docker/certbot, and links `iw` to `/usr/local/bin`.

Manual install (Python 3.9+ already present):

```bash
./setup-agent.sh
source .venv/bin/activate
iw device
```

**Proxy app (uvicorn, etc.) — typical flow:**

```bash
iw project register /path/to/app --name myapp
# start your app (systemd or uvicorn on 127.0.0.1:8000)
sudo iw project publish myapp --domain app.example.com --backend-port 8000
```

## Documentation

| Doc | Description |
|-----|-------------|
| [src/agent/README.md](src/agent/README.md) | Agent install, modules, development |
| [docs/AGENT-COMMANDS.md](docs/AGENT-COMMANDS.md) | Full `iw` command reference (flags, `-i` keys, examples) |

## Repository layout

```
infrawatch/
├── README.md
├── setup-agent.sh
├── docs/
│   └── AGENT-COMMANDS.md
└── src/
    └── agent/
        ├── README.md
        ├── requirements.txt
        ├── pyproject.toml
        └── src/iw_agent/
            ├── cli/           # iw command, TUI, output
            ├── core/          # actions, audit log, paths
            └── modules/
                ├── device/
                ├── network/
                ├── processes/
                ├── docker/
                ├── nginx/
                ├── ssl/
                ├── cron/
                └── project/
```

## Requirements

- Python 3.9+
- Linux or macOS for development (production targets Linux servers)
- Some commands need elevated privileges (`sudo iw …`) or optional services (Docker, nginx)

## License

Part of the InfraWatch project.
