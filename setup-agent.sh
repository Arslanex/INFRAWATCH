#!/usr/bin/env bash
#
# InfraWatch agent — one-command setup.
#
#   sudo ./setup-agent.sh --system    # fresh Linux server
#   ./setup-agent.sh                  # local / existing Python
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$REPO_ROOT/src/agent"
VENV="$REPO_ROOT/.venv"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"
IW="$VENV/bin/iw"

SYSTEM_INSTALL=0
SKIP_CAPABILITIES=0
SKIP_SYSTEM_DEPS=0

# ── Terminal render (fixed layout, matches iw CLI style) ─────────────────────

UI_PLAIN=0
[[ -n "${NO_COLOR:-}" || ! -t 1 ]] && UI_PLAIN=1

UI_B="" UI_D="" UI_G="" UI_Y="" UI_R="" UI_M="" UI_N=""
if [[ "$UI_PLAIN" -eq 0 ]]; then
    UI_B=$'\033[1m'
    UI_D=$'\033[2m'
    UI_G=$'\033[32m'
    UI_Y=$'\033[33m'
    UI_R=$'\033[31m'
    UI_M=$'\033[35m'
    UI_N=$'\033[0m'
fi

UI_W=44
UI_BOX_BORDER=""

ui_header() {
    local title="$1"
    local subtitle="${2:-}"
    ui_box_open info "${UI_B}${title}${UI_N}"
    if [[ -n "$subtitle" ]]; then
        ui_box_field "About" "$subtitle"
    fi
    ui_box_close
}

ui_summary() {
    ui_box_open info "${UI_B}Summary:${UI_N}"
    ui_box_line "$1"
    ui_box_close
}

ui_box_open() {
    local tone="$1"
    local header="$2"
    UI_BOX_BORDER="$UI_M"
    case "$tone" in
        ok)   UI_BOX_BORDER="$UI_G" ;;
        warn) UI_BOX_BORDER="$UI_Y" ;;
        bad)  UI_BOX_BORDER="$UI_R" ;;
    esac
    printf '\n   %s┌─ %s%s\n' "$UI_BOX_BORDER" "$header" "$UI_N"
}

ui_box_line() {
    printf '   %s│%s %s\n' "$UI_BOX_BORDER" "$UI_N" "$1"
}

ui_box_field() {
    ui_box_line "${UI_B}${1}:${UI_N} ${2}"
}

ui_box_close() {
    printf '   %s└%s\n\n' "$UI_BOX_BORDER" "$(printf '─%.0s' $(seq 1 "$UI_W"))"
}

ui_phase() {
    printf '  %s·%s %s' "$UI_D" "$UI_N" "$1"
}

ui_phase_ok() {
    printf '  %sok%s\n' "$UI_G" "$UI_N"
}

ui_phase_skip() {
    printf '  %sskip%s\n' "$UI_D" "$UI_N"
}

ui_phase_warn() {
    printf '  %swarn%s\n' "$UI_Y" "$UI_N"
}

ui_die() {
    ui_box_open bad "Setup failed"
    ui_box_line "$1"
    ui_box_close
    exit 1
}

usage() {
    cat <<'USAGE'
Usage: ./setup-agent.sh [options]

Installs system Python (on Linux as root), creates a venv, and installs the
InfraWatch agent CLI (iw) with all Python dependencies.

Options:
  --system              Recommended on servers (root): install OS packages,
                        link /usr/local/bin/iw, and grant Linux capabilities
                        for network/process collectors.
  --skip-system-deps    Skip apt/dnf/brew OS package installation.
  --skip-capabilities   Do not apply Linux capabilities (even with --system).
  -h, --help            Show this help.

Examples:
  sudo ./setup-agent.sh --system
  ./setup-agent.sh
USAGE
}

# ── Setup logic ──────────────────────────────────────────────────────────────

while [ $# -gt 0 ]; do
    case "$1" in
        --system)              SYSTEM_INSTALL=1; shift ;;
        --skip-system-deps)    SKIP_SYSTEM_DEPS=1; shift ;;
        --skip-capabilities)   SKIP_CAPABILITIES=1; shift ;;
        -h|--help)             usage; exit 0 ;;
        *)                     usage >&2; ui_die "unknown option: $1" ;;
    esac
done

if [ "$SYSTEM_INSTALL" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
    ui_die "--system requires root — run: sudo ./setup-agent.sh --system"
fi

[ -d "$AGENT_DIR" ] || ui_die "missing $AGENT_DIR — run from the infrawatch repo root"
[ -f "$AGENT_DIR/requirements.txt" ] || ui_die "missing $AGENT_DIR/requirements.txt"
[ -f "$AGENT_DIR/pyproject.toml" ] || ui_die "missing $AGENT_DIR/pyproject.toml"

os_name="$(uname -s)"
mode_label="local install"
[[ "$SYSTEM_INSTALL" -eq 1 ]] && mode_label="system install"

ui_header "InfraWatch setup" "Install the iw agent CLI on this machine"
ui_summary "$mode_label · $os_name · $(id -un 2>/dev/null || echo unknown)"

install_linux_packages_apt() {
    ui_phase "System packages (apt)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        python3 python3-venv python3-pip python3-dev \
        build-essential libffi-dev libssl-dev libcap2-bin \
        cron ca-certificates curl git
    if [ "$SYSTEM_INSTALL" -eq 1 ]; then
        apt-get install -y -qq nginx docker.io 2>/dev/null || {
            apt-get install -y -qq nginx 2>/dev/null || true
        }
    fi
    ui_phase_ok
}

install_linux_packages_dnf() {
    ui_phase "System packages (dnf)"
    dnf install -y -q \
        python3 python3-pip python3-devel gcc \
        libffi-devel openssl-devel libcap cronie \
        ca-certificates curl git
    if [ "$SYSTEM_INSTALL" -eq 1 ]; then
        dnf install -y -q nginx docker 2>/dev/null || {
            dnf install -y -q nginx 2>/dev/null || true
        }
    fi
    ui_phase_ok
}

install_linux_packages_apk() {
    ui_phase "System packages (apk)"
    apk add --no-cache -q \
        python3 py3-pip python3-dev build-base \
        libffi-dev openssl-dev libcap-utils busybox-suid \
        ca-certificates curl git
    ui_phase_ok
}

install_macos_packages() {
    command -v brew >/dev/null 2>&1 || ui_die "Homebrew not found — install from https://brew.sh"
    ui_phase "System packages (brew)"
    brew install python@3.12 libcap 2>/dev/null || brew install python@3.12
    ui_phase_ok
}

install_system_dependencies() {
    if [ "$SKIP_SYSTEM_DEPS" -eq 1 ]; then
        ui_phase "System packages"
        ui_phase_skip
        return 0
    fi

    case "$os_name" in
        Linux)
            if [ "$(id -u)" -ne 0 ]; then
                ui_die "OS packages need root on Linux — run: sudo ./setup-agent.sh --system"
            fi
            if command -v apt-get >/dev/null 2>&1; then
                install_linux_packages_apt
            elif command -v dnf >/dev/null 2>&1; then
                install_linux_packages_dnf
            elif command -v apk >/dev/null 2>&1; then
                install_linux_packages_apk
            else
                ui_die "unsupported Linux distro — install Python 3.9+ manually"
            fi
            ;;
        Darwin)
            if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
                install_macos_packages
            else
                ui_phase "System packages"
                ui_phase_skip
            fi
            ;;
        *)
            ui_phase "System packages"
            ui_phase_skip
            ;;
    esac
}

python_usable() {
    local candidate="$1"
    command -v "$candidate" >/dev/null 2>&1 &&
        "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)' &&
        "$candidate" -c 'import venv' 2>/dev/null
}

find_python() {
    local candidate=""
    for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
        if python_usable "$candidate"; then
            command -v "$candidate"
            return 0
        fi
    done
    return 1
}

if [ "$SYSTEM_INSTALL" -eq 1 ] || { [ "$os_name" = "Linux" ] && [ "$(id -u)" -eq 0 ]; }; then
    install_system_dependencies
fi

python_bin=""
if ! python_bin="$(find_python)"; then
    if [ "$os_name" = "Linux" ] && [ "$(id -u)" -ne 0 ]; then
        ui_die "Python 3.9+ with venv not found — run: sudo ./setup-agent.sh --system"
    fi
    ui_die "Python 3.9+ with venv support is required but was not found"
fi

ui_phase "$("$python_bin" --version 2>&1)"
ui_phase_ok

ui_phase "Virtual environment"
if [ ! -d "$VENV" ]; then
    "$python_bin" -m venv "$VENV"
else
    :
fi
ui_phase_ok

ui_phase "Python packages"
"$PIP" install -q --upgrade pip
"$PIP" install -q -r "$AGENT_DIR/requirements.txt"
"$PIP" install -q "$AGENT_DIR"
ui_phase_ok

ui_phase "Verify install"
[ -x "$IW" ] || ui_die "iw was not installed into $VENV/bin"
"$IW" --help >/dev/null
"$PYTHON" -c "import psutil, pydantic, httpx, crontab, cryptography" ||
    ui_die "a required Python package failed to import"
ui_phase_ok

capability_note=""
if [ "$SYSTEM_INSTALL" -eq 1 ]; then
    ui_phase "System-wide iw"
    install -m 0755 "$IW" /usr/local/bin/iw
    ui_phase_ok

    if [ "$SKIP_CAPABILITIES" -eq 0 ] && [ "$os_name" = "Linux" ] && command -v setcap >/dev/null 2>&1; then
        ui_phase "Linux capabilities"
        if setcap cap_net_admin,cap_sys_ptrace+ep "$PYTHON" 2>/dev/null; then
            capability_note="capabilities applied to $PYTHON"
            ui_phase_ok
        else
            capability_note="setcap failed — use sudo iw for full network/process data"
            ui_phase_warn
        fi
    fi
fi

# ── Done ─────────────────────────────────────────────────────────────────────

cli_path="$IW"
[[ "$SYSTEM_INSTALL" -eq 1 ]] && cli_path="/usr/local/bin/iw"

ui_box_open ok "Ready"
ui_box_field "CLI" "$cli_path"
ui_box_field "Venv" "$VENV"
if [[ -n "$capability_note" ]]; then
    ui_box_field "Note" "$capability_note"
fi
ui_box_close

ui_box_open info "Next steps"
ui_box_line "Activate: source $VENV/bin/activate"
ui_box_line "Try:      iw device · iw ports · iw nginx · iw certs"
ui_box_line "Help:     iw --help"
if [ "$SYSTEM_INSTALL" -eq 0 ] && [ "$os_name" = "Linux" ]; then
    ui_box_line "Server:   sudo ./setup-agent.sh --system"
fi
if [ "$SYSTEM_INSTALL" -eq 1 ] && [ "$os_name" = "Darwin" ]; then
    ui_box_line "macOS:    sudo iw connections for full network data"
fi
ui_box_close
