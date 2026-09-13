# Agent Commands

Short reference for the `iw` CLI (InfraWatch agent).

## Global

| Command | Description |
|---------|-------------|
| `iw` | Interactive menu |
| `iw --menu` | Same as above |
| `iw --help` | List all commands |

**Flags (most commands):**

| Flag | Description |
|------|-------------|
| `--json` | Machine-readable JSON output |
| `--plain` | No colors (plain text) |

---

## Device

Server health: CPU, memory, disks.

| Command | Description |
|---------|-------------|
| `iw device` | Full overview (system + workload + disks) |
| `iw metrics` | CPU cores, RAM, load, network totals |
| `iw disks` | Disk usage by mount point |

---

## Network

Listening ports and outbound connections.

| Command | Description |
|---------|-------------|
| `iw network` | Ports + outbound connections |
| `iw ports` | Listening ports only |
| `iw connections` | Outbound connections only |

**Flags:** `--limit N` (default: 20 on network/connections)

**Note:** May need `sudo iw ports` or `sudo iw connections` without elevated privileges.

---

## Processes

| Command | Description |
|---------|-------------|
| `iw processes` | Top processes by CPU usage |

**Flags:** `--limit N` (default: 10)

---

## Docker

| Command | Description |
|---------|-------------|
| `iw containers` | Docker containers (grouped by compose project) |

**Flags:** `--limit N` · `--timeout SEC` · `--socket PATH`

---

## Nginx

| Command | Description |
|---------|-------------|
| `iw nginx` | Live + disabled virtual hosts |
| `iw nginx-config` | `nginx -T` dump and certificate paths |

**Flags:** `--timeout SEC` · `--binary PATH` · `nginx-config --show-stdout`

---

## SSL

| Command | Description |
|---------|-------------|
| `iw certs` | SSL certificates on disk |

**Flags:** `--certbot-dir PATH` · extra cert paths as arguments

---

## Cron

| Command | Description |
|---------|-------------|
| `iw cron` | Scheduled cron jobs |
| `iw cron-history` | Recent job run results |

**Flags (cron-history):** `--log-dir PATH` · `--tail N`

---

## Quick examples

```bash
iw device
iw ports
iw containers
iw nginx
iw certs
iw processes
sudo iw connections
iw device --json
iw metrics --plain
```
