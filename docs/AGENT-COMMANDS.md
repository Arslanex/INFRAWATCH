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

**Config editor (`-i` → site → Edit configuration):**

| Section | What you can change |
|---------|---------------------|
| Redirects | Toggle HTTP→HTTPS and www→apex redirect blocks |
| Backend / proxy | Set `proxy_pass` or remove it |
| Static files | Set `root`, `index`, `try_files` (standard or SPA preset), or remove `try_files` |
| Security headers | Presets: **Basic** (frame/options/referrer), **Strict** (+ HSTS, needs HTTPS), **None** (remove managed headers) |

Changes are written to the site config file, then nginx is tested and reloaded (with confirm prompts).

**New site wizard (`-i` → Create new site):**

| Step | What you choose |
|------|-----------------|
| Domain | e.g. `app.example.com` |
| Type | Static files or reverse proxy |
| Static | Document root, try_files (standard or SPA) |
| Proxy | Backend URL (`proxy_pass`) |
| Enable | Symlink into `sites-enabled` and reload nginx |

Config is written to `sites-available/<domain>`. Use **Obtain HTTPS certificate** on the site afterward if needed.

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
