#!/bin/bash
# Build a portable .AppImage for vipergirls-viewer using Docker.
#
# Usage:
#   ./packaging/scripts/build-appimage.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-appimage.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg docker appimage "$@"
