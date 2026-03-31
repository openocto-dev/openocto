#!/usr/bin/env bash
# OpenOcto installer for macOS and Linux.
#
# Works in two modes:
#   Remote:  curl -sSL https://raw.githubusercontent.com/.../install.sh | bash
#   Local:   ./scripts/install.sh   (from the project root)

set -euo pipefail

REPO_URL="https://github.com/openocto-dev/openocto.git"
MIN_PYTHON="3.10"

# --- Colors ---
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${CYAN}$*${NC}"; }
ok()    { echo -e "${GREEN}✓ $*${NC}"; }
warn()  { echo -e "${YELLOW}⚠ $*${NC}"; }
fail()  { echo -e "${RED}✗ $*${NC}"; exit 1; }

# --- Check Python ---
find_python() {
    for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$cmd" &>/dev/null; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            local major minor
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
                echo "$cmd"
                return 0
            fi
        fi
    done
    return 1
}

# --- Detect project root ---
find_project_root() {
    # If running from within the repo, find pyproject.toml
    local dir="$PWD"
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/pyproject.toml" ] && grep -q "openocto" "$dir/pyproject.toml" 2>/dev/null; then
            echo "$dir"
            return 0
        fi
        dir=$(dirname "$dir")
    done
    return 1
}

# --- Main ---
echo ""
echo -e "${BOLD}${CYAN}🐙 OpenOcto Installer${NC}"
echo ""

# 1. Check Python
info "Checking Python..."
PYTHON=$(find_python) || fail "Python $MIN_PYTHON+ is required. Install it from https://python.org"
PYTHON_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
ok "Found Python $PYTHON_VER ($PYTHON)"

# 2. Determine project directory (local or remote)
if PROJECT_DIR=$(find_project_root 2>/dev/null); then
    info "Found project at $PROJECT_DIR"
    cd "$PROJECT_DIR"
else
    # Remote mode: clone the repo
    command -v git &>/dev/null || fail "git is required. Install it first."
    INSTALL_DIR="${OPENOCTO_DIR:-$HOME/openocto}"

    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing installation in $INSTALL_DIR..."
        git -C "$INSTALL_DIR" pull --quiet
        ok "Updated"
    else
        info "Cloning OpenOcto to $INSTALL_DIR..."
        git clone --quiet "$REPO_URL" "$INSTALL_DIR"
        ok "Cloned"
    fi

    cd "$INSTALL_DIR"
fi

# 3. Create venv
if [ ! -d ".venv" ]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv .venv
    ok "Virtual environment created"
fi

# 4. Install
info "Installing dependencies..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -e .
ok "Installed"

# 5. Verify
VERSION=$(.venv/bin/openocto --version 2>&1 | tail -1)
ok "$VERSION"

# 6. Make `openocto` available system-wide
OCTO_BIN="$(pwd)/.venv/bin/openocto"
SYMLINK_PLACED=false

# Try /usr/local/bin first (always in PATH, no restart needed)
if [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
    ln -sf "$OCTO_BIN" /usr/local/bin/openocto
    ok "Symlink created: /usr/local/bin/openocto"
    SYMLINK_PLACED=true
elif sudo -n true 2>/dev/null; then
    sudo ln -sf "$OCTO_BIN" /usr/local/bin/openocto
    ok "Symlink created: /usr/local/bin/openocto (sudo)"
    SYMLINK_PLACED=true
fi

# Fallback: write to shell rc file
if [ "$SYMLINK_PLACED" = false ]; then
    OCTO_BIN_DIR="$(pwd)/.venv/bin"
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        zsh)  RC_FILE="$HOME/.zshrc" ;;
        bash) RC_FILE="$HOME/.bashrc" ;;
        *)    RC_FILE="" ;;
    esac

    if [ -n "$RC_FILE" ]; then
        if ! grep -qF "$OCTO_BIN_DIR" "$RC_FILE" 2>/dev/null; then
            printf '\n# OpenOcto\nexport PATH="%s:$PATH"\n' "$OCTO_BIN_DIR" >> "$RC_FILE"
        fi
        export PATH="$OCTO_BIN_DIR:$PATH"
        ok "Added openocto to PATH in $RC_FILE"
        echo ""
        warn "Restart your terminal or run:  source $RC_FILE"
    else
        export PATH="$(pwd)/.venv/bin:$PATH"
        warn "Unknown shell — add manually:  export PATH=\"$(pwd)/.venv/bin:\$PATH\""
    fi
fi

# 7. Install openwakeword (optional, for always-on wake word mode)
echo ""
read -r -p "$(echo -e "${CYAN}Install wake word detection (\"Hey Octo!\")? [y/N]: ${NC}")" INSTALL_WW
if [[ "$INSTALL_WW" =~ ^[Yy]$ ]]; then
    info "Installing openwakeword..."
    .venv/bin/pip install --quiet "openwakeword>=0.6.0" && ok "openwakeword installed" || warn "Failed to install openwakeword (optional — wake word won't work)"
else
    info "Skipping wake word detection (you can enable it later with: pip install openwakeword)"
fi

# 9. Install claude-max-api-proxy (optional, for Claude subscription users)
if command -v npm &>/dev/null; then
    if ! command -v claude-max-api &>/dev/null; then
        info "Installing claude-max-api-proxy (for Claude subscription users)..."
        # Fix npm cache permissions (common issue on macOS when npm was run with sudo)
        [ -d "$HOME/.npm" ] && chown -R "$(whoami)" "$HOME/.npm" 2>/dev/null || true
        npm install -g claude-max-api-proxy --quiet && ok "claude-max-api-proxy installed" || warn "Failed to install claude-max-api-proxy (optional)"
    else
        ok "claude-max-api-proxy already installed"
    fi
else
    warn "npm not found — skipping claude-max-api-proxy (optional, needed for Claude subscription mode)"
fi

# 10. Run setup wizard
echo ""
info "Starting setup wizard..."
echo ""
.venv/bin/openocto setup
