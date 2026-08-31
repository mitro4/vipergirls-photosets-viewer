#!/bin/bash
# Shared build logic for vipergirls-viewer native packages.
#
# Sourced by the docker wrappers (build-<fmt>.sh) and podman wrappers
# (build-<fmt>-podman.sh). Each format differs only in Dockerfile path, image
# tag, an optional --target stage, and a post-extract step.
#
# Usage (from a wrapper):
#   source "$(dirname "${BASH_SOURCE[0]}")/_common.sh"
#   build_pkg docker deb "$@"     # or: build_pkg podman appimage "$@"
#
# build_pkg <runner> <format> [version]
#   runner : docker | podman
#   format : deb | rpm | appimage | windows
set -euo pipefail

_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

build_pkg() {
    local runner="$1"
    local fmt="$2"
    local version="${3:-${VERSION:-0.1.5}}"

    local project_root output_dir
    project_root="$(cd "$_COMMON_DIR/../.." && pwd)"
    output_dir="$project_root/dist-packages"

    local dockerfile image_tag target artifact label
    case "$fmt" in
        deb)
            dockerfile="deb/Dockerfile"
            image_tag="viper-viewer-deb:${version}"
            target=""
            artifact="*.deb"
            label=".deb"
            ;;
        rpm)
            dockerfile="rpm/Dockerfile"
            image_tag="viper-viewer-rpm:${version}"
            target=""
            artifact="*.rpm"
            label=".rpm"
            ;;
        appimage)
            dockerfile="appimage/Dockerfile"
            image_tag="viper-viewer-appimage:${version}"
            target=""
            artifact="*.AppImage"
            label=".AppImage"
            ;;
        windows)
            dockerfile="windows/Dockerfile"
            image_tag="viper-viewer-windows:${version}"
            target="installer"
            artifact="*win-x64*"
            label="Windows packages"
            ;;
        arch)
            dockerfile="arch/Dockerfile"
            image_tag="viper-viewer-arch:${version}"
            target=""
            artifact="*.pkg.tar.zst"
            label=".pkg.tar.zst (CachyOS/Arch)"
            ;;
        *)
            echo "build_pkg: unknown format '$fmt' (expected deb|rpm|appimage/windows/arch)" >&2
            exit 1
            ;;
    esac

    if ! command -v "$runner" >/dev/null 2>&1; then
        echo "✗ '$runner' not found in PATH. Install it or pick the other runner." >&2
        exit 127
    fi

    mkdir -p "$output_dir"

    echo "▸ Building $label  (version $version) via $runner…"
    local build_args=(
        build
        -f "$project_root/packaging/docker/$dockerfile"
        --build-arg VERSION="$version"
        -t "$image_tag"
    )
    if [ -n "$target" ]; then
        build_args+=(--target "$target")
    fi
    build_args+=("$project_root")

    "$runner" "${build_args[@]}"

    echo "▸ Extracting artifact…"
    local cid
    cid=$("$runner" create "$image_tag")
    "$runner" cp "$cid:/dist/." "$output_dir/"
    "$runner" rm "$cid" >/dev/null

    # AppImages need the executable bit to run (FUSE mount).
    if [ "$fmt" = "appimage" ]; then
        chmod +x "$output_dir"/*.AppImage 2>/dev/null || true
    fi

    echo ""
    echo "✓ Done — $label in $output_dir/"
    # shellcheck disable=SC2086  # artifact glob must expand unquoted
    ls -lh "$output_dir"/$artifact 2>/dev/null || true
}
