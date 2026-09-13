# InfraWatch

InfraWatch monitors your servers from the inside out: a lightweight agent reads what each host is doing, a central service stores and alerts on that data, and a dashboard lets you inspect and operate your infrastructure from one place.

This repository is under active development. **Only the agent collectors are implemented today.** Other components will be added here as they land.

## Architecture (planned)

```
┌─────────────┐     WebSocket      ┌─────────────┐     HTTP/API    ┌─────────────┐
│   Agent     │ ─────────────────► │    Core     │ ◄────────────── │  Dashboard  │
│  (on host)  │      snapshots     │   (server)  │                 │  (console)  │
└─────────────┘                    └─────────────┘                 └─────────────┘
```

| Component | Path | Status |
|-----------|------|--------|
| **Agent** | [`src/agent/`](src/agent/) | **In progress** — collectors + CLI |
| Core (server) | `src/server/` | Planned |
| Dashboard (console) | `src/console/` | Planned |

The agent runs on each monitored machine. It collects read-only snapshots (processes, ports, Docker, nginx, certificates, cron, device metrics) and will stream them to core. Core persists the data and sends commands back (start a project, renew a certificate, apply nginx config, and similar). The dashboard is the operator UI on top of core.

## What works today

The agent package provides:

- **Collectors** — modular Python APIs under `src/agent/src/iw_agent/modules/`
- **CLI** — `iw` for local inspection on a host (`iw device`, `iw ports`, `iw containers`, …)
- **Typed errors** — per-service exception classes for privilege and availability failures

Not yet in this repo: the long-running daemon, WebSocket transport to core, command executors (nginx, certbot, cron, projects), and install/service packaging.

## Quick start (agent)

From the repository root on a **fresh Linux server**:

```bash
sudo ./setup-agent.sh --system
iw device
iw ports
```

The setup script installs system Python, build libraries, pip dependencies, and links `iw` to `/usr/local/bin`.

Manual install (Python 3.9+ already present):

```bash
./setup-agent.sh
source .venv/bin/activate
iw device
```

Full agent documentation: **[src/agent/README.md](src/agent/README.md)**

## Repository layout

```
infrawatch/
├── README.md           # this file — project overview
└── src/
    └── agent/          # server agent (collectors + iw CLI)
        ├── README.md
        ├── requirements.txt
        ├── pyproject.toml
        └── src/iw_agent/
            ├── cli/
            ├── core/
            └── modules/
                ├── device/
                ├── network/
                ├── processes/
                ├── docker/
                ├── nginx/
                ├── ssl/
                └── cron/
```

## Requirements

- Python 3.9+
- Linux or macOS for development (production targets Linux servers)
- Some agent commands need elevated privileges (network connections, system crontabs) or optional services (Docker, nginx)

## License

Part of the InfraWatch project.
