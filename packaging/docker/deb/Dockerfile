#
# Builds a .deb package for vipergirls-viewer.
#
# Four stages:
#   1. Build the React SPA (node)
#   2. Self-contained Python runtime with all deps (python:3.12-slim)
#   3. Download Electron runtime (Chromium)
#   4. Assemble the .deb payload and run dpkg-deb (debian:bookworm-slim)
#
# Usage (from project root):
#   docker build -f packaging/docker/deb/Dockerfile -t viper-deb --build-arg VERSION=0.1.0 .
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

# ── Stage 4: Assemble .deb ───────────────────────────────────────────────────
FROM debian:bookworm-slim
ARG VERSION=0.1.0
ARG ARCH=amd64

COPY --from=backend /pkg/ /pkg/
COPY --from=electron /electron/ /pkg/opt/vipergirls-viewer/electron/

# Electron app entry point.
COPY electron/ /pkg/opt/vipergirls-viewer/electron/resources/app/

# Launcher script + systemd unit + desktop entry.
COPY packaging/common/run.sh /pkg/opt/vipergirls-viewer/backend/run.sh
COPY packaging/common/vipergirls-viewer.service /pkg/lib/systemd/system/
COPY packaging/common/vipergirls-viewer.desktop /pkg/usr/share/applications/
COPY packaging/common/postinst /pkg/DEBIAN/postinst
COPY packaging/common/prerm /pkg/DEBIAN/prerm
COPY packaging/common/postrm /pkg/DEBIAN/postrm

RUN chmod 755 /pkg/DEBIAN/postinst /pkg/DEBIAN/prerm /pkg/DEBIAN/postrm \
    /pkg/opt/vipergirls-viewer/backend/run.sh

# Generate DEBIAN/control.
RUN mkdir -p /pkg/DEBIAN && \
    SIZE_KB=$(du -sk /pkg | cut -f1) && \
    { \
      echo "Package: vipergirls-viewer"; \
      echo "Version: ${VERSION}"; \
      echo "Architecture: ${ARCH}"; \
      echo "Maintainer: mitro4"; \
      echo "Installed-Size: ${SIZE_KB}"; \
      echo "Depends: adduser, libgtk-3-0, libnss3, libasound2, libxss1, libxtst6, libgbm1, libdrm2, libatspi2.0-0, libnotify4, xdg-utils"; \
      echo "Section: net"; \
      echo "Priority: optional"; \
      echo "Description: ViperGirls Photo Sets Viewer"; \
      echo " Web-based photo set viewer for the ViperGirls forum."; \
      echo " Bundles Python runtime + Electron (Chromium) - no system deps required."; \
    } > /pkg/DEBIAN/control

# Build the .deb.
RUN mkdir -p /dist && \
    dpkg-deb --build --root-owner-group /pkg /dist/vipergirls-viewer_${VERSION}_${ARCH}.deb && \
    ls -lh /dist/
