#!/bin/bash
# Build all native packages (deb, rpm, AppImage, Windows, Arch/CachyOS) in
# sequence using Docker.
#
# Usage:
#   ./packaging/scripts/build-all.sh [version]
#   VERSION=0.2.0 ./packaging/scripts/build-all.sh
#
# The builds share the same frontend + backend stages (Docker BuildKit layer
# cache means stages 1-2 are only built once across all of them).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-${VERSION:-0.1.5}}"

FAILED=()

for fmt in deb rpm appimage windows arch; do
    echo ""
    echo "═══ Building $fmt ═══"
    if ! "$SCRIPT_DIR/build-$fmt.sh" "$VERSION"; then
        echo "✗ $fmt build failed"
        FAILED+=("$fmt")
    fi
done

echo ""
echo "═══ Summary ═══"
if [ ${#FAILED[@]} -eq 0 ]; then
    echo "✓ All packages built successfully."
else
    echo "✗ Failed: ${FAILED[*]}"
    exit 1
fi
