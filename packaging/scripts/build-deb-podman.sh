#!/bin/bash
# Build a .deb package for vipergirls-viewer using Podman (OCI, daemonless).
#
# Usage:
#   ./packaging/scripts/build-deb-podman.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-deb-podman.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg podman deb "$@"
