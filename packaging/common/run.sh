#!/bin/bash
# Launcher for vipergirls-viewer (deb / rpm installation).
#
# The package bundles a complete Python installation (copied from the
# python:3.12-slim-bookworm Docker image) and an Electron runtime (Chromium).
#
# Modes:
#   run.sh            # desktop mode: Electron window (Chromium) + Python backend
#   run.sh --no-gui   # server mode : uvicorn in foreground (for systemd / headless)
set -euo pipefail

APP_ROOT="/opt/vipergirls-viewer"
PYTHON_ROOT="$APP_ROOT/python"
ELECTRON_DIR="$APP_ROOT/electron"

export PYTHONHOME="$PYTHON_ROOT"
export PYTHONPATH="$APP_ROOT/backend"
export LD_LIBRARY_PATH="$PYTHON_ROOT/lib:${LD_LIBRARY_PATH:-}"

if [ "${1:-}" = "--no-gui" ]; then
    # Server-only mode (systemd): shared data dir, owned by the service user.
    export DATA_DIR="${VIPER_DATA_DIR:-/var/lib/vipergirls-viewer}"
    cd "$APP_ROOT/backend"
    exec "$PYTHON_ROOT/bin/python3.12" -m app.launcher --no-gui
fi

# GUI mode (desktop launcher): per-user data dir so the app doesn't need
# root-owned /var/lib for writes. Falls back to ~/.local/share.
USER_DATA="${XDG_DATA_HOME:-$HOME/.local/share}/vipergirls-viewer"
mkdir -p "$USER_DATA"
export DATA_DIR="$USER_DATA"
export VIPERGIRLS_APP_ROOT="$APP_ROOT"
cd "$ELECTRON_DIR"
exec ./electron --no-sandbox "$@"
