#!/bin/bash
# Build an .rpm package for vipergirls-viewer using Docker.
#
# Usage:
#   ./packaging/scripts/build-rpm.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-rpm.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
build_pkg docker rpm "$@"
