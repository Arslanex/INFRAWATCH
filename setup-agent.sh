#!/usr/bin/env bash
#
# InfraWatch agent — one-command setup.
#
# Fresh Linux server (installs Python + system libs + pip deps):
#
#   sudo ./setup-agent.sh --system
#
# Machine that already has Python 3.9+:
#
#   ./setup-agent.sh
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

say()  { printf '  %s\n' "$*"; }
step() { printf '\n==> %s\n' "$*"; }
die()  { printf 'setup-agent.sh: %s\n' "$*" >&2; exit 1; }

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

while [ $# -gt 0 ]; do
    case "$1" in
        --system)              SYSTEM_INSTALL=1; shift ;;
        --skip-system-deps)    SKIP_SYSTEM_DEPS=1; shift ;;
        --skip-capabilities)   SKIP_CAPABILITIES=1; shift ;;
        -h|--help)             usage; exit 0 ;;
        *)                     usage >&2; die "unknown option: $1" ;;
    esac
done

if [ "$SYSTEM_INSTALL" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
    die "--system requires root — run: sudo ./setup-agent.sh --system"
fi

[ -d "$AGENT_DIR" ] || die "missing $AGENT_DIR — run this script from the infrawatch repo root"
[ -f "$AGENT_DIR/requirements.txt" ] || die "missing $AGENT_DIR/requirements.txt"
[ -f "$AGENT_DIR/pyproject.toml" ] || die "missing $AGENT_DIR/pyproject.toml"

os_name="$(uname -s)"

install_linux_packages_apt() {
    step "Installing system packages (apt)"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        python3 \
        python3-venv \
        python3-pip \
        python3-dev \
        build-essential \
        libffi-dev \
        libssl-dev \
        libcap2-bin \
        cron \
        ca-certificates \
        curl \
        git
    if [ "$SYSTEM_INSTALL" -eq 1 ]; then
        apt-get install -y -qq nginx docker.io 2>/dev/null || {
            apt-get install -y -qq nginx 2>/dev/null || true
            say "note: docker.io not installed — add Docker manually if needed"
        }
    fi
}

install_linux_packages_dnf() {
    step "Installing system packages (dnf)"
    dnf install -y \
        python3 \
        python3-pip \
        python3-devel \
        gcc \
        libffi-devel \
        openssl-devel \
        libcap \
        cronie \
        ca-certificates \
        curl \
        git
    if [ "$SYSTEM_INSTALL" -eq 1 ]; then
        dnf install -y nginx docker 2>/dev/null || {
            dnf install -y nginx 2>/dev/null || true
            say "note: docker not installed — add Docker manually if needed"
        }
    fi
}

install_linux_packages_apk() {
    step "Installing system packages (apk)"
    apk add --no-cache \
        python3 \
        py3-pip \
        python3-dev \
        build-base \
        libffi-dev \
        openssl-dev \
        libcap-utils \
        busybox-suid \
        ca-certificates \
        curl \
        git
}

install_macos_packages() {
    if ! command -v brew >/dev/null 2>&1; then
        die "Homebrew not found — install from https://brew.sh or install Python 3.9+ manually"
    fi
    step "Installing system packages (brew)"
    brew install python@3.12 libcap 2>/dev/null || brew install python@3.12
}

install_system_dependencies() {
    if [ "$SKIP_SYSTEM_DEPS" -eq 1 ]; then
        say "skipping OS package installation (--skip-system-deps)"
        return 0
    fi

    case "$os_name" in
        Linux)
            if [ "$(id -u)" -ne 0 ]; then
                die "OS packages need root on Linux — run: sudo ./setup-agent.sh --system"
            fi
            if command -v apt-get >/dev/null 2>&1; then
                install_linux_packages_apt
            elif command -v dnf >/dev/null 2>&1; then
                install_linux_packages_dnf
            elif command -v apk >/dev/null 2>&1; then
                install_linux_packages_apk
            else
                die "unsupported Linux distro — install Python 3.9+, python3-venv, pip, gcc, libffi, openssl, libcap manually"
            fi
            ;;
        Darwin)
            if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
                install_macos_packages
            fi
            ;;
        *)
            say "unknown OS — assuming Python 3.9+ is already installed"
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
if python_bin="$(find_python)"; then
    :
else
    if [ "$os_name" = "Linux" ] && [ "$(id -u)" -ne 0 ]; then
        die "Python 3.9+ with venv not found — run: sudo ./setup-agent.sh --system"
    fi
    die "Python 3.9+ with venv support is required but was not found"
fi

step "Using Python"
say "$("$python_bin" --version) at $python_bin"

step "Creating virtual environment"
if [ ! -d "$VENV" ]; then
    "$python_bin" -m venv "$VENV"
else
    say "reusing existing venv at $VENV"
fi

step "Installing Python packages"
"$PIP" install -q --upgrade pip
"$PIP" install -q -r "$AGENT_DIR/requirements.txt"
"$PIP" install -q "$AGENT_DIR"

step "Verifying install"
[ -x "$IW" ] || die "iw was not installed into $VENV/bin"
"$IW" --help >/dev/null
"$PYTHON" -c "import psutil, pydantic, httpx, crontab, cryptography" ||
    die "a required Python package failed to import"

if [ "$SYSTEM_INSTALL" -eq 1 ]; then
    step "Installing system-wide iw"
    install -m 0755 "$IW" /usr/local/bin/iw
    say "linked /usr/local/bin/iw"

    if [ "$SKIP_CAPABILITIES" -eq 0 ] && [ "$os_name" = "Linux" ] && command -v setcap >/dev/null 2>&1; then
        step "Granting Linux capabilities for collectors"
        setcap cap_net_admin,cap_sys_ptrace+ep "$PYTHON" 2>/dev/null || {
            say "warning: setcap failed — run iw with sudo for full network/process data"
        }
        if getcap "$PYTHON" >/dev/null 2>&1; then
            getcap "$PYTHON" | sed 's/^/  /'
        fi
    fi
fi

step "Done"
cat <<EOF

  InfraWatch agent is ready.

  Python packages: psutil, pydantic, httpx, python-crontab, cryptography
  CLI entry point:  $IW

  Activate the venv:
    source $VENV/bin/activate

  Run the CLI:
    iw device
    iw ports
    iw containers
    iw nginx
    iw certs
    iw --help

EOF

if [ "$SYSTEM_INSTALL" -eq 0 ] && [ "$os_name" = "Linux" ]; then
    cat <<EOF
  On a fresh Linux server use:
    sudo ./setup-agent.sh --system

EOF
fi

if [ "$SYSTEM_INSTALL" -eq 1 ] && [ "$os_name" = "Darwin" ]; then
    cat <<EOF
  Note: macOS still requires sudo for full network connection data.

EOF
fi
