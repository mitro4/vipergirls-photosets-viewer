#!/bin/bash
# Build a pacman .pkg.tar.zst for vipergirls-viewer (CachyOS / Arch) using Docker.
#
# Usage:
#   ./packaging/scripts/build-arch.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-arch.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg docker arch "$@"
