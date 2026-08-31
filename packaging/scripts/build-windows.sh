#!/bin/bash
# Build a Windows portable ZIP + NSIS installer for vipergirls-viewer using Docker.
#
# Usage:
#   ./packaging/scripts/build-windows.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-windows.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg docker windows "$@"
