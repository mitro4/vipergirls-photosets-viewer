#
# Builds a pacman .pkg.tar.zst for vipergirls-viewer (CachyOS / Arch Linux).
#
# Stages 1-3 are identical to the deb/rpm builds (React SPA + self-contained
# Python runtime + downloaded Electron). Stage 4 runs makepkg on archlinux to
# produce a native pacman package the user installs with `pacman -U`.
#
# Usage (from project root):
#   docker build -f packaging/docker/arch/Dockerfile -t viper-arch --build-arg VERSION=0.1.0 .
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

# Bundle the entire Python installation (interpreter + stdlib + site-packages
# + libpython).  This makes the package fully self-contained — no system
# Python is needed on the target.
RUN mkdir -p /pkg/opt/vipergirls-viewer/python && \
    cp -a /usr/local/. /pkg/opt/vipergirls-viewer/python/ && \
    find /pkg/opt/vipergirls-viewer/python -depth -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
    rm -rf /pkg/opt/vipergirls-viewer/python/include

# Generate the application icon (Pillow is already installed above).
COPY packaging/common/make-icon.py /tmp/
RUN mkdir -p /pkg/usr/share/icons/hicolor/256x256/apps && \
    python /tmp/make-icon.py && \
    mv /tmp/vipergirls-viewer.png /pkg/usr/share/icons/hicolor/256x256/apps/

# ── Stage 3: Download Electron runtime ───────────────────────────────────────
FROM alpine:3.20 AS electron
ARG ELECTRON_VERSION=31.3.1
RUN apk add --no-cache wget unzip
RUN wget -q "https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/electron-v${ELECTRON_VERSION}-linux-x64.zip" -O /tmp/electron.zip && \
    mkdir -p /electron && \
    unzip -q /tmp/electron.zip -d /electron && \
    rm /tmp/electron.zip && \
    chmod +x /electron/electron

# ── Stage 4: Build .pkg.tar.zst via makepkg ──────────────────────────────────
FROM archlinux:latest
ARG VERSION=0.1.0

# base-devel pulls makepkg + fakeroot + zstd + bsdtar(libarchive).
RUN pacman -Syu --noconfirm --needed base-devel && \
    pacman -Scc --noconfirm

# makepkg refuses to run as root — build as an unprivileged user.
RUN useradd -m -s /bin/bash builduser

# Stage the assembled payload (the icon already lives under /pkg/usr/...).
COPY --from=backend /pkg/ /staging/pkg/
COPY --from=electron /electron/ /staging/pkg/opt/vipergirls-viewer/electron/
COPY electron/ /staging/pkg/opt/vipergirls-viewer/electron/resources/app/
COPY packaging/common/run.sh /staging/pkg/opt/vipergirls-viewer/backend/run.sh
# Arch convention: systemd units live under /usr/lib/systemd/system (not /lib).
RUN mkdir -p /staging/pkg/usr/lib/systemd/system
COPY packaging/common/vipergirls-viewer.service /staging/pkg/usr/lib/systemd/system/
COPY packaging/common/vipergirls-viewer.desktop /staging/pkg/usr/share/applications/
RUN chmod +x /staging/pkg/opt/vipergirls-viewer/backend/run.sh

# PKGBUILD + pacman install hooks.
COPY packaging/docker/arch/PKGBUILD /build/PKGBUILD
COPY packaging/docker/arch/vipergirls-viewer.install /build/vipergirls-viewer.install
RUN sed -i "s/^pkgver=.*/pkgver=${VERSION}/" /build/PKGBUILD && \
    chown -R builduser:builduser /build && \
    mkdir -p /dist && chown builduser:builduser /dist

USER builduser
WORKDIR /build
# makepkg wraps package() in its OWN internal fakeroot (default option), so the
# archive entries come out owned by root:0 without us wrapping makepkg itself —
# an external `fakeroot -- makepkg` trips makepkg's "don't run as root" guard
# (libfakeroot intercepts geteuid() → returns 0). Run as the unprivileged user.
# --nodeps: the depends (gtk3, nss, …) target the host, not the build container
# — skip the check so makepkg doesn't try to install them here.
RUN makepkg -f --nodeps --noconfirm && \
    cp *.pkg.tar.zst /dist/ && \
    ls -lh /dist/
