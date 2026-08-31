#
# Builds an .rpm package for vipergirls-viewer via fpm.
#
# Four stages (same frontend + backend + Electron, different packager):
#   1. Build the React SPA (node)
#   2. Self-contained Python runtime (python:3.12-slim)
#   3. Download Electron runtime
#   4. fpm on Fedora to create the .rpm
#
# Usage (from project root):
#   docker build -f packaging/docker/rpm/Dockerfile -t viper-rpm --build-arg VERSION=0.1.0 .
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

# ── Stage 4: Build .rpm via fpm ──────────────────────────────────────────────
FROM fedora:39
ARG VERSION=0.1.0
ARG ARCH=x86_64

RUN dnf install -y --setopt=install_weak_deps=False \
        ruby ruby-devel rubygem-json make gcc rpm-build wget && \
    gem install fpm --no-document && \
    dnf clean all

COPY --from=backend /pkg/ /pkg/
COPY --from=electron /electron/ /pkg/opt/vipergirls-viewer/electron/
COPY electron/ /pkg/opt/vipergirls-viewer/electron/resources/app/
COPY packaging/common/run.sh /pkg/opt/vipergirls-viewer/backend/run.sh
COPY packaging/common/vipergirls-viewer.service /pkg/lib/systemd/system/
COPY packaging/common/vipergirls-viewer.desktop /pkg/usr/share/applications/
COPY packaging/common/postinst /tmp/postinst
COPY packaging/common/prerm /tmp/prerm
COPY packaging/common/postrm /tmp/postrm
RUN chmod 755 /tmp/postinst /tmp/prerm /tmp/postrm \
    /pkg/opt/vipergirls-viewer/backend/run.sh

RUN mkdir -p /dist && \
    fpm -s dir -t rpm \
        -n vipergirls-viewer \
        -v "${VERSION}" \
        --iteration 1 \
        -a "${ARCH}" \
        --url "https://github.com/mitro4/vipergirls-photosets-viewer" \
        --description "ViperGirls Photo Sets Viewer - web-based photo set viewer" \
        --license MIT \
        --depends shadow-utils \
        --depends gtk3 \
        --depends nss \
        --depends alsa-lib \
        --depends at-spi2-core \
        --depends libdrm \
        --depends mesa-libgbm \
        --depends libnotify \
        --after-install /tmp/postinst \
        --before-remove /tmp/prerm \
        --after-remove /tmp/postrm \
        -p /dist/vipergirls-viewer-${VERSION}-1.${ARCH}.rpm \
        /pkg/opt/=/opt/ \
        /pkg/usr/=/usr/ \
        /pkg/lib/=/lib/ && \
    ls -lh /dist/
