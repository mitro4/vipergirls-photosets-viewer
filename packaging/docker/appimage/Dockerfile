#
# Builds a portable .AppImage for vipergirls-viewer.
#
# Four stages:
#   1. Build the React SPA (node)
#   2. Self-contained Python runtime (python:3.12-slim)
#   3. Download Electron runtime (Chromium)
#   4. Assemble AppDir + run appimagetool (ubuntu:22.04)
#
# The AppImage bundles a full Python runtime + Electron (Chromium). On launch
# (AppRun) Electron starts the Python backend on localhost:8000 and renders the
# SPA in a Chromium BrowserWindow. Data is stored per-user in
# $XDG_DATA_HOME/vipergirls-viewer.
#
# Usage (from project root):
#   docker build -f packaging/docker/appimage/Dockerfile -t viper-appimage --build-arg VERSION=0.1.0 .
#

# ── Stage 1: Frontend ─────────────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime + dependencies ───────────────────────────────────
FROM python:3.12-slim-bookworm AS backend
WORKDIR /build

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backend/app/ /pkg/opt/vipergirls-viewer/backend/app/
COPY --from=frontend /build/dist/ /pkg/opt/vipergirls-viewer/backend/static/

RUN mkdir -p /pkg/opt/vipergirls-viewer/python && \
    cp -a /usr/local/. /pkg/opt/vipergirls-viewer/python/ && \
    find /pkg/opt/vipergirls-viewer/python -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    rm -rf /pkg/opt/vipergirls-viewer/python/include

COPY packaging/common/make-icon.py /tmp/
RUN python /tmp/make-icon.py && \
    mkdir -p /pkg/icons && \
    mv /tmp/vipergirls-viewer.png /pkg/icons/

# ── Stage 3: Download Electron runtime ───────────────────────────────────────
FROM alpine:3.20 AS electron
ARG ELECTRON_VERSION=31.3.1
RUN apk add --no-cache wget unzip
RUN wget -q "https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/electron-v${ELECTRON_VERSION}-linux-x64.zip" -O /tmp/electron.zip && \
    mkdir -p /electron && \
    unzip -q /tmp/electron.zip -d /electron && \
    rm /tmp/electron.zip && \
    chmod +x /electron/electron

# ── Stage 4: Build AppImage ──────────────────────────────────────────────────
FROM ubuntu:22.04
ARG VERSION=0.1.0
ARG ARCH=x86_64

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget ca-certificates file && \
    rm -rf /var/lib/apt/lists/*

# Download appimagetool (continuous build — single static binary).
RUN wget -q "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-${ARCH}.AppImage" \
        -O /usr/local/bin/appimagetool && \
    chmod +x /usr/local/bin/appimagetool && \
    cd /tmp && /usr/local/bin/appimagetool --appimage-extract && \
    rm -rf /usr/local/bin/appimagetool

# Assemble the AppDir.
COPY --from=backend /pkg/ /appdir/
COPY --from=electron /electron/ /appdir/opt/vipergirls-viewer/electron/
COPY electron/ /appdir/opt/vipergirls-viewer/electron/resources/app/
COPY packaging/common/AppRun /appdir/AppRun
COPY packaging/common/vipergirls-viewer.desktop /appdir/vipergirls-viewer.desktop
RUN chmod 755 /appdir/AppRun

# Place the icon at AppDir root (appimagetool picks it up from .desktop Icon=).
RUN cp /appdir/icons/vipergirls-viewer.png /appdir/vipergirls-viewer.png && \
    ln -sf vipergirls-viewer.png /appdir/.DirIcon && \
    rm -rf /appdir/icons

# Adapt the desktop file for AppImage: Exec=AppRun, add version tag.
RUN sed -i \
    -e 's|^Exec=.*|Exec=AppRun|' \
    -e "/^X-AppImage-Version/d" \
    /appdir/vipergirls-viewer.desktop && \
    echo "X-AppImage-Version=${VERSION}" >> /appdir/vipergirls-viewer.desktop

# Build the AppImage (use extracted appimagetool — FUSE is unavailable in Docker).
RUN mkdir -p /dist && \
    /tmp/squashfs-root/AppRun /appdir \
        "/dist/vipergirls-viewer-${VERSION}-${ARCH}.AppImage" \
        --no-appstream && \
    ls -lh /dist/
