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

**Interactive:**

| Entry | Description |
|-------|-------------|
| `iw nginx -i` | Browse sites, pick actions (read/write with confirm + audit log) |
| `iw` → nginx → **2** | Same site manager from the main menu |
| `-i` → **Create new site** | Wizard: domain, static or proxy, enable + reload |
| `--dry-run` | Preview write actions without applying them |
| `--staging` | Let's Encrypt test certificates (also prompted in `-i`) |

Reload, enable, and disable run through the module executor (`sudo` required). `Test nginx config` runs `nginx -t`.

**SSL wizard (ngnix executor):**

| Situation | Action in menu |
|-----------|----------------|
| NO SSL | Obtain HTTPS certificate (precheck → certbot → attach nginx → HTTP redirect → reload) |
| EXPIRING / EXPIRED | Renew certificate |
| MISMATCH | Attach certificate to nginx |

Action params: `domain`, `email` (obtain), `method` (`auto`/`nginx`/`webroot`), `staging`, `webroot`.

**Site hub (`-i` → site):** HTTPS (if needed) · Configure · Enable/Disable · Reload · More

**Configure (`-i` → site → Configure site):**

| Group | Sub-sections |
|-------|----------------|
| Traffic | Backend, Paths, Static files |
| Domain & redirects | Names/ports, Redirects |
| Security | Header presets (Basic / Strict / None) |

Navigation: `b` back · `q` quit

Changes are written to the site config file, then nginx is tested and reloaded (with confirm prompts).

**New site wizard (`-i` → Create new site):**

| Step | What you choose |
|------|-----------------|
| Domain | e.g. `app.example.com` |
| Names | Optional `www` alias and extra domains (comma-separated) |
| HTTP port | Standard `80` or custom port |
| Type | Static files or reverse proxy |
| Static | Document root, try_files (standard or SPA) |
| Proxy | Backend URL (`proxy_pass`) |
| Enable | Symlink into `sites-enabled` and reload nginx |
| HTTPS now | Optional: certbot obtain → attach SSL → HTTP redirect → reload |

Config is written to `sites-available/<domain>`. **HTTPS now** runs the same chain as **Set up HTTPS** on the site hub (requires enable + reload first).

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
sudo iw nginx -i --dry-run
```
