#!/bin/bash
# Build a .deb package for vipergirls-viewer using Docker.
#
# Usage:
#   ./packaging/scripts/build-deb.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-deb.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg docker deb "$@"
