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
| `-i` / `--interactive` | Browse and run actions (confirm + audit log) |
| `--dry-run` | Preview write actions without applying them |

**Main menu (`iw`):** commands with a manager offer **1** view (read-only) or **2** manage (`-i`). Applies to: nginx, cron, containers, processes, certs, project.

Write actions are logged to `logs/actions.log`.

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

**Interactive:**

| Entry | Description |
|-------|-------------|
| `iw processes -i` | Full-screen card picker: select process → action menu (details, kill) |
| `--dry-run` | Preview kill without sending a signal |

**Process hub (`-i` → process):** View details · Kill process (type `YES` to confirm)

Kill sends SIGTERM by default; you can opt into SIGKILL if TERM fails. Protected PIDs (init, agent) are refused. `sudo` required for kill.

Picker: `↑↓` select · Enter manage · `q` quit. Action menu: `b` back · `q` quit.

---

## Docker

| Command | Description |
|---------|-------------|
| `iw containers` | Docker containers (grouped by compose project) |

**Flags:** `--limit N` · `--timeout SEC` · `--socket PATH` · `--tail N`

**Interactive:**

| Entry | Description |
|-------|-------------|
| `iw containers -i` | Full-screen card picker: select container → action menu (start/stop/restart, logs, details) |
| `--dry-run` | Preview write actions without applying them |

**Container hub (`-i` → container):** Restart/Stop or Start · Logs · View details

Picker: `↑↓` select · Enter manage · `q` quit. Action menu: `b` back · `q` quit.

Docker socket access is required (often `sudo` or membership in the `docker` group).

---

## Nginx

| Command | Description |
|---------|-------------|
| `iw nginx` | Sites nginx serves — domains, HTTPS, ports, backends |
| `iw nginx-config` | Advanced: runs `nginx -T`, lists SSL cert file paths |

**When to use which:**

- **`iw nginx`** — everyday check: which sites are live, off, HTTP vs HTTPS.
- **`iw nginx-config`** — troubleshooting only: did `nginx -T` succeed? which cert files are referenced in config? Add `--show-stdout` for the full raw dump.

**Flags:** `--timeout SEC` · `--binary PATH` · `nginx-config --show-stdout`

**Interactive (structural editor):**

| Entry | Description |
|-------|-------------|
| `iw nginx -i` | Site picker (status boxes, ↑↓ + Enter) → config editor |
| `iw nginx -i --site app.example.com` | Open that site directly |
| `iw` → nginx → **2** | Same from the main menu |
| `--dry-run` | Preview saves and actions without root (no disk writes) |
| `--staging` | Let's Encrypt test certificates |

**Site picker keys:**

| Keys | Action |
|------|--------|
| ↑↓ | Select a site |
| Enter | Open config editor |
| `o` | **Enable** or **disable** site (symlink in/out of `sites-enabled` + reload) |
| `q` | Quit |

Off sites (`sites-available` only) show *Action: o enable site* on the card. Live sites: *o disable*.

**Numbered fallback** (non-TTY): pick site → **Edit config** or **Enable/Disable site**.

**Editor layout:** left pane = config tree (line-by-line); right pane = selected directive detail.

| Keys | Action |
|------|--------|
| ↑↓ | Move between rows / blocks |
| → / ← | Expand / fold blocks |
| Enter | Edit directive (typed form or raw line) |
| `a` / `A` | Add after / add inside block (`+ add` rows everywhere) |
| `s` | Save (`nginx -t` + atomic write + rollback on failure) |
| `o` | Enable or disable this site (same as picker) |
| `x` | Actions: test, reload, enable/disable, HTTPS, diff, revert |
| `/` `n` `N` | Search, next/previous match |
| `?` | Help overlay |
| `q` | Quit |

**New site:** picker → **New site** → minimal wizard (domain, type, enable) → **opens in the editor** for the rest.

HTTPS: use **x → Obtain HTTPS** in the editor (or optional HTTPS during new-site creation).

Requires `sudo` for real saves on the server; `--dry-run` works without root.

---

## SSL

| Command | Description |
|---------|-------------|
| `iw certs` | SSL certificates on disk |

**Flags:** `--certbot-dir PATH` · extra cert paths as arguments

**Interactive:**

| Entry | Description |
|-------|-------------|
| `iw certs -i` | Full-screen card picker: select cert → actions, or obtain new certificate |
| `--dry-run` | Preview certbot commands without running them |
| `--staging` | Let's Encrypt test certificates |

**Certificate hub (`-i` → cert):** Renew (certbot) · View details

Summary shows expiring/expired warnings. **Obtain new certificate** is the last card; runs certbot certonly (nginx or webroot).

Picker: `↑↓` select · Enter open · `q` quit. Action menu: `b` back · `q` quit.

---

## Cron

| Command | Description |
|---------|-------------|
| `iw cron` | Scheduled cron jobs |
| `iw cron-history` | Recent job run results |

**Flags:** `--log-dir PATH` · `--tail N`

**Interactive:**

| Entry | Description |
|-------|-------------|
| `iw cron -i` | Job picker (status boxes, ↑↓ + Enter) → action menu |
| `--dry-run` | Preview write actions without applying them |

**Job hub (`-i` → job):** Run now · Enable/Disable (user crontabs only) · View history · Tail output log · View details · Show command

System crontab entries (`/etc/crontab`, `/etc/cron.d`) are read-only in `-i`. User crontab jobs can be enabled or disabled (`sudo` required).

Picker: `↑↓` select · Enter manage · `q` quit. Action menu: `b` back · `q` quit.

---

## Projects

Register app repositories, deploy compose stacks, or **publish** proxy/static apps via nginx.

| Command | Description |
|---------|-------------|
| `iw project` | List registered projects (same as `list`) |
| `iw project list` | List registered projects |
| `iw project register <source>` | Register existing local clone or clone from git (alias: `add`) |
| `iw project detect <name>` | Re-detect stack type and ports (after repo layout changes) |
| `iw project publish <name>` | Publish via nginx (proxy/static) or deploy compose (alias: `deploy`) |
| `iw project stop <name>` | Run docker compose down |
| `iw project -i` | Card picker: register → publish/deploy · nginx editor · stop |

**Flags:**

| Flag | Description |
|------|-------------|
| `--workspace PATH` | Projects directory (default: `projects` or `$INFRAWATCH_PROJECTS_DIR`) |
| `--name NAME` | Project name for `add` (default: repo or folder name) |
| `--save` | Write detection results to `.infrawatch.json` |
| `--timeout SEC` | Git clone timeout for `add` (default: 120) / compose timeout for `deploy` (default: 600) |
| `--dry-run` | Preview deploy/stop without running compose or nginx |
| `--no-build` | Skip `docker compose --build` on deploy |
| `--force` | Deploy even if published host ports look busy or certbot precheck warns |
| `--domain DOMAIN` | Create or update nginx site for this domain |
| `--https` | Obtain Let's Encrypt certificate after nginx is ready |
| `--email EMAIL` | Contact email for Let's Encrypt (required with `--https`) |
| `--no-www` | Do not add `www.<domain>` to `server_name` |
| `--staging` | Use Let's Encrypt staging certificates |
| `--backend-port PORT` | Override backend port for nginx `proxy_pass` |

**Detected types (P1):** `docker-compose` · `dockerfile` · `static` · `proxy`

Each project is stored under the workspace with a manifest:

```
projects/myapp/
  .infrawatch.json
  repo/              # clone or symlink to source
```

**Examples:**

```bash
# Register an existing clone (does not start the app)
iw project register /path/to/local-app --name myapp

# docker-compose
iw project publish myapp
iw project publish myapp --domain app.example.com --https --email admin@example.com
iw project stop myapp

# proxy app (uvicorn, etc.) — start the app yourself first
uvicorn main:app --host 127.0.0.1 --port 8000
iw project publish myapp --domain app.example.com --backend-port 8000
iw project publish myapp --domain app.example.com --backend-port 8000 --https --email admin@example.com

# static site
iw project publish mystatic --domain static.example.com

iw project list --json
```

**Workflow by type:**

| Type | What InfraWatch does | What you do |
|------|----------------------|-------------|
| `docker-compose` | `docker compose up`, optional nginx + HTTPS | `register` → `publish` / `deploy` |
| `static` | nginx serves files from repo | `register` → `publish --domain …` |
| `proxy` | nginx → `localhost:PORT` + optional HTTPS | **Start app** (uvicorn/systemd) → `register` → `publish --domain … --backend-port …` |

**Publish vs nginx `-i`:** use `iw project publish` when the app is registered in the workspace (manifest tracks domain and type). Use `iw nginx -i` only to edit nginx config without the project registry.

**Re-detect:** only needed after the repo gains compose/static files — `iw project detect myapp --save`.

Nginx reuses existing site configs when the domain is already registered. HTTPS chains certbot obtain → attach SSL → reload (same as `iw nginx` create wizard).

**Interactive (`-i`):** register → **Publish to web** / **Deploy stack** wizard · Edit nginx · Stop · Re-detect (advanced). Use `--dry-run` to preview steps.

**Proxy publish** checks that something is listening on `--backend-port` unless `--force`.

**Keep uvicorn running (systemd example):** InfraWatch publish wires nginx only — use systemd (or similar) so the app survives logout and reboot.

```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=myapp (uvicorn)
After=network.target

[Service]
Type=simple
User=deploy
WorkingDirectory=/path/to/myapp
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now myapp.service
sudo iw project publish myapp --domain app.example.com --backend-port 8000
```

**Server setup:** `sudo ./setup-agent.sh --system` installs nginx, docker, and certbot on supported Linux distros.

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

# interactive managers (card pickers)
sudo iw nginx -i
sudo iw cron -i
iw containers -i
sudo iw processes -i
sudo iw certs -i
iw project -i

# project: register clone, start app, publish via nginx
iw project register /path/to/app --name myapp
sudo iw project publish myapp --domain app.example.com --backend-port 8000
sudo iw project -i --dry-run
sudo iw nginx -i --dry-run
```
