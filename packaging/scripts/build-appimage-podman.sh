#!/bin/bash
# Build a portable .AppImage for vipergirls-viewer using Podman (OCI, daemonless).
#
# Usage:
#   ./packaging/scripts/build-appimage-podman.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-appimage-podman.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg podman appimage "$@"
