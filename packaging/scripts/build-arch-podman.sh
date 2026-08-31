#!/bin/bash
# Build a pacman .pkg.tar.zst for vipergirls-viewer (CachyOS / Arch) using Podman.
#
# Usage:
#   ./packaging/scripts/build-arch-podman.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-arch-podman.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg podman arch "$@"
