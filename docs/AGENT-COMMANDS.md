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

**Main menu (`iw`):** commands with a manager offer **1** view (read-only) or **2** manage (`-i`). Applies to: nginx, cron, containers, processes, certs.

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
| `iw processes -i` | Browse top processes, view details or kill with confirm + audit log |
| `--dry-run` | Preview kill without sending a signal |

**Process hub (`-i` → process):** View details · Kill process (type `YES` to confirm)

Kill sends SIGTERM by default; you can opt into SIGKILL if TERM fails. Protected PIDs (init, agent) are refused. `sudo` required for kill.

Navigation: `b` back · `q` quit

---

## Docker

| Command | Description |
|---------|-------------|
| `iw containers` | Docker containers (grouped by compose project) |

**Flags:** `--limit N` · `--timeout SEC` · `--socket PATH` · `--tail N`

**Interactive:**

| Entry | Description |
|-------|-------------|
| `iw containers -i` | Browse containers, start/stop/restart with confirm + audit log |
| `--dry-run` | Preview write actions without applying them |

**Container hub (`-i` → container):** Restart/Stop or Start · Logs · More

Containers are grouped by compose project in the list. Docker socket access is required (often `sudo` or membership in the `docker` group).

Navigation: `b` back · `q` quit

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
| `iw nginx -i` | Site picker → full-screen config editor |
| `iw nginx -i --site app.example.com` | Open that site directly |
| `iw` → nginx → **2** | Same from the main menu |
| `--dry-run` | Preview saves and actions without root (no disk writes) |
| `--staging` | Let's Encrypt test certificates |

**Editor layout:** left pane = config tree (line-by-line); right pane = selected directive detail.

| Keys | Action |
|------|--------|
| ↑↓ | Move between rows / blocks |
| → / ← | Expand / fold blocks |
| Enter | Edit directive (typed form or raw line) |
| `a` / `A` | Add after / add inside block (`+ add` rows everywhere) |
| `s` | Save (`nginx -t` + atomic write + rollback on failure) |
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
| `iw certs -i` | Browse certificates, renew or obtain with confirm + audit log |
| `--dry-run` | Preview certbot commands without running them |
| `--staging` | Let's Encrypt test certificates |

**Certificate hub (`-i` → cert):** Renew (certbot) · View details · More

List shows expiring/expired warnings at the top. **Obtain new certificate** runs certbot certonly (nginx plugin or webroot) without requiring an nginx site wizard.

Navigation: `b` back · `q` quit

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
| `iw cron -i` | Browse jobs, run/enable/disable with confirm + audit log |
| `--dry-run` | Preview write actions without applying them |

**Job hub (`-i` → job):** Run now · Enable/Disable (user crontabs only) · View history · More

System crontab entries (`/etc/crontab`, `/etc/cron.d`) are read-only in `-i`. User crontab jobs can be enabled or disabled (`sudo` required).

Navigation: `b` back · `q` quit

---

## Projects

Register app repositories and detect how they should be deployed.

| Command | Description |
|---------|-------------|
| `iw project` | List registered projects (same as `list`) |
| `iw project list` | List registered projects |
| `iw project add <source>` | Clone git repo or register local directory |
| `iw project detect <name>` | Detect stack type and check ports |
| `iw project deploy <name>` | Deploy compose/static/proxy projects with optional nginx + HTTPS |
| `iw project stop <name>` | Run docker compose down |
| `iw project -i` | Interactive project manager (add, detect, deploy, stop) |

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
iw project add https://github.com/user/myapp.git
iw project add /path/to/local-app --name myapp
iw project detect myapp
iw project detect myapp --save
iw project deploy myapp
iw project deploy myapp --domain app.example.com
iw project deploy myapp --domain app.example.com --https --email admin@example.com
iw project deploy myapp --dry-run --domain app.example.com --https --email admin@example.com
iw project deploy mystatic --domain static.example.com
iw project stop myapp
iw project list --json
```

**Deploy flow:**

| Type | Steps |
|------|-------|
| `docker-compose` | port check → `docker compose up -d --build` → health check → optional nginx proxy → optional HTTPS |
| `static` | nginx static site (`--domain` required) → optional HTTPS |
| `proxy` | nginx reverse proxy to `--backend-port` (`--domain` required) → optional HTTPS |

Nginx reuses existing site configs when the domain is already registered. HTTPS chains certbot obtain → attach SSL → reload (same as `iw nginx` create wizard).

**Interactive (`-i`):** project list → detect · deploy wizard (domain, backend port, HTTPS) · stop · add project. Use `--dry-run` to preview deploy steps.

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

# interactive managers
sudo iw nginx -i
sudo iw cron -i
iw containers -i
sudo iw processes -i
sudo iw certs -i
iw project -i
sudo iw project -i --dry-run
sudo iw nginx -i --dry-run
```
