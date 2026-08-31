#
# Builds a Windows portable ZIP + NSIS installer for vipergirls-viewer.
#
# Everything runs natively on Linux — no Wine, no Windows host needed:
#
#   1. Build the React SPA (node)
#   2. Download Windows Python embeddable + pip download all deps targeting
#      win_amd64 (all have prebuilt wheels on PyPI)
#   3. Download Electron for Windows (win32-x64 zip)
#   4. Assemble the folder structure, create portable ZIP
#   5. Run native makensis (from apt) to create an NSIS .exe installer
#
# Usage (from project root):
#   docker build -f packaging/docker/windows/Dockerfile -t viper-windows --build-arg VERSION=0.1.0 .
#

# ── Stage 1: Frontend ─────────────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Windows Python runtime + dependencies ───────────────────────────
FROM python:3.12-slim-bookworm AS backend
WORKDIR /build

# Download the Windows embeddable Python (a self-contained zip — no installer,
# no registry, just extract and run python.exe).
ARG PY_WIN_VERSION=3.12.10
RUN apt-get update && apt-get install -y --no-install-recommends wget unzip && \
    rm -rf /var/lib/apt/lists/*
RUN wget -q "https://www.python.org/ftp/python/${PY_WIN_VERSION}/python-${PY_WIN_VERSION}-embed-amd64.zip" -O /tmp/py-win.zip && \
    mkdir -p /pkg/python && \
    unzip -q /tmp/py-win.zip -d /pkg/python && \
    rm /tmp/py-win.zip

# Bootstrap pip into the embeddable Python. The embeddable package ships a
# python312._pth file with "import site" commented out — pip needs it enabled.
RUN sed -i 's/^#import site/import site/' /pkg/python/python312._pth
# The ._pth file completely overrides PYTHONPATH (Python docs). Since the
# backend source lives in ../backend (relative to python.exe), we must add
# it to ._pth so `python -m app.launcher` can find the `app` package.
RUN echo "../backend" >> /pkg/python/python312._pth
# get-pip.py works on any platform (it's pure Python).
RUN wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py && \
    /usr/local/bin/python /tmp/get-pip.py --no-warn-script-location && \
    rm /tmp/get-pip.py

# Install all dependencies targeting win_amd64. Every dep in requirements.txt
# has a prebuilt Windows wheel on PyPI (verified: curl_cffi, Pillow, lxml all
# ship win_amd64 wheels), so --only-binary=:all: works without compilation.
# We download the wheels and unzip their contents directly into the embeddable
# Python's Lib/site-packages (the embeddable zip has no Lib/ — we create it).
COPY backend/requirements.txt ./
# uvicorn[standard] pulls uvloop (Linux-only, no win_amd64 wheel). pip download
# can't evaluate conditional markers for cross-platform targets, so strip the
# [standard] extra for Windows. uvicorn runs fine on plain asyncio for a
# single-user desktop app.
RUN sed 's/uvicorn\[standard\]/uvicorn/' requirements.txt > requirements-win.txt
RUN mkdir -p /pkg/python/Lib/site-packages && \
    pip download --no-cache-dir \
        --platform win_amd64 \
        --python-version 3.12 \
        --only-binary=:all: \
        --dest /tmp/wheels \
        -r requirements-win.txt && \
    for whl in /tmp/wheels/*.whl; do \
        echo "Unpacking $(basename "$whl")..."; \
        unzip -qo "$whl" -d /tmp/whl-extract; \
        cp -a /tmp/whl-extract/* /pkg/python/Lib/site-packages/ 2>/dev/null || true; \
        rm -rf /tmp/whl-extract; \
    done && \
    rm -rf /tmp/wheels

# Copy backend source + built frontend.
COPY backend/app/ /pkg/backend/app/
COPY --from=frontend /build/dist/ /pkg/backend/static/

# ── Stage 3: Download Electron for Windows ───────────────────────────────────
FROM alpine:3.20 AS electron
ARG ELECTRON_VERSION=31.3.1
RUN apk add --no-cache wget unzip
RUN wget -q "https://github.com/electron/electron/releases/download/v${ELECTRON_VERSION}/electron-v${ELECTRON_VERSION}-win32-x64.zip" -O /tmp/electron.zip && \
    mkdir -p /electron && \
    unzip -q /tmp/electron.zip -d /electron && \
    rm /tmp/electron.zip

# ── Stage 4: Assemble portable ZIP ───────────────────────────────────────────
FROM ubuntu:22.04 AS portable
ARG VERSION=0.1.0

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends zip && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /staging

# Python runtime
COPY --from=backend /pkg/python/ vipergirls-viewer/python/

# Backend source + static SPA
COPY --from=backend /pkg/backend/ vipergirls-viewer/backend/

# Electron runtime (Windows binaries)
COPY --from=electron /electron/ vipergirls-viewer/electron/

# Electron app code (main.js + package.json + icon)
COPY electron/ vipergirls-viewer/electron/resources/app/

# Generate icon
COPY packaging/common/make-icon.py /tmp/
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pil && \
    python3 /tmp/make-icon.py && \
    mv /tmp/vipergirls-viewer.png vipergirls-viewer/electron/resources/app/icon.png && \
    cp vipergirls-viewer/electron/resources/app/icon.png vipergirls-viewer/vipergirls-viewer.png && \
    rm -rf /var/lib/apt/lists/*

# README for the portable folder
RUN cat > vipergirls-viewer/README.txt <<'EOF'
ViperGirls Viewer ${VERSION}

To start the application, run electron\electron.exe
(or use the Start Menu / Desktop shortcut if installed via setup.exe).
Data is stored in %APPDATA%\vipergirls-viewer.
EOF

# Create the portable ZIP
RUN mkdir -p /dist && \
    zip -r "/dist/vipergirls-viewer-${VERSION}-win-x64-portable.zip" vipergirls-viewer/ && \
    ls -lh /dist/

# ── Stage 5: NSIS installer ──────────────────────────────────────────────────
FROM ubuntu:22.04 AS installer
ARG VERSION=0.1.0

ENV DEBIAN_FRONTEND=noninteractive

# NSIS is available as a native Linux package in Ubuntu — no Wine needed.
# makensis runs natively and produces a Windows .exe installer.
RUN apt-get update && apt-get install -y --no-install-recommends nsis && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy the portable staging from the previous stage.
COPY --from=portable /staging/ /staging/
COPY --from=portable /dist/ /dist/

# Write the NSIS installer script.
RUN cat > /tmp/installer.nsi <<'NSISEOF'
!define APPNAME "ViperGirls Viewer"
!define APPVER "VERSION_PLACEHOLDER"
!define APPDIRNAME "vipergirls-viewer"

Name "${APPNAME}"
OutFile "/dist/vipergirls-viewer-${APPVER}-win-x64-setup.exe"
InstallDir "$PROGRAMFILES64\${APPDIRNAME}"
InstallDirRegKey HKLM "Software\${APPDIRNAME}" "InstallDir"
RequestExecutionLevel admin
ShowInstDetails show
SetCompressor /SOLID lzma

Page directory
Page instfiles

UninstPage uninstConfirm
UninstPage instfiles

Section "Install"
    SetOutPath "$INSTDIR"
    File /r "/staging/vipergirls-viewer\*.*"

    WriteRegStr HKLM "Software\${APPDIRNAME}" "InstallDir" "$INSTDIR"

    CreateDirectory "$SMPROGRAMS\${APPNAME}"
    CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\electron\electron.exe" "--no-sandbox" "$INSTDIR\electron\resources\app\icon.png" 0
    CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\electron\electron.exe" "--no-sandbox" "$INSTDIR\electron\resources\app\icon.png" 0

    WriteUninstaller "$INSTDIR\Uninstall.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir /r "$INSTDIR"
    RMDir /r "$SMPROGRAMS\${APPNAME}"
    Delete "$DESKTOP\${APPNAME}.lnk"
    DeleteRegKey HKLM "Software\${APPDIRNAME}"
SectionEnd
NSISEOF

# Substitute version, then build.
RUN sed -i "s/VERSION_PLACEHOLDER/${VERSION}/" /tmp/installer.nsi && \
    makensis /tmp/installer.nsi && \
    ls -lh /dist/
