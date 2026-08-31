# Packaging and distributing the application

The current architecture is a **web application**: a Python/FastAPI backend (forum parsing,
image proxying, ZIP assembly, a persistent download queue, and downloading into folders) +
a React SPA + Caddy (serves static assets and proxies the API). The persistent download queue
lives in `app/services/download_queue.py` (service) and `app/api/download_queue.py` (router).
This is described in `AGENTS.md`.

For desktop distributions, you need to package **both the frontend and the backend** into a single
executable bundle. Below are practical approaches for each format.

---

## Table of Contents

1. [Building via Docker (working method — deb / rpm / AppImage / Windows)](#1-building-via-docker-working-method--deb--rpm--appimage--windows)
   - [How it works](#how-it-works)
   - [Usage](#usage)
   - [Package structure](#package-structure)
   - [Installation and running](#installation-and-running)
   - [Before building](#before-building)
   - [Podman instead of Docker](#podman-instead-of-docker)
2. [Alternative: PyInstaller + Tauri/Electron (manual)](#2-alternative-pyinstaller--tauielectron-manual)
   - [Preparation: backend into a standalone binary (PyInstaller)](#preparation-backend-into-a-standalone-binary-pyinstaller)
   - [Desktop shell (Tauri)](#desktop-shell-tauri)
   - [Alternative: Electron](#alternative-electron)
   - [Publishing the frontend to npm](#publishing-the-frontend-to-npm)
3. [Summary table of tools](#3-summary-table-of-tools)

---

## 1. Building via Docker (working method — deb / rpm / AppImage / Windows)

The `packaging/` directory contains ready-made scripts and Dockerfiles that build native packages
**reproducibly in Docker** — without installing any local tools (dpkg-deb / fpm / appimagetool). You
only need Docker on the host.

### How it works

Each format (`deb`, `rpm`, `appimage`) has its own Dockerfile with four stages:

1. **frontend** (`node:20-slim`) — `npm ci && npm run build` → `dist/`.
2. **backend** (`python:3.12-slim-bookworm`) — installs all dependencies from
   `backend/requirements.txt` into the system Python, then copies the **entire**
   `/usr/local/` (interpreter + stdlib + site-packages + libpython) into the payload.
   Caches (`__pycache__`) and headers (`include/`) are stripped. System .so
   libraries (libssl, libcrypto, libfontconfig, ...) are **not bundled** — they come from
   the target OS (pip packages include their native deps in the wheels).
3. **electron** (`alpine:3.20`) — downloads the prebuilt Electron runtime
   (Chromium + Node.js, ~100 MB zip) from GitHub releases and unpacks it.
4. **package** — a format-specific image (`debian:bookworm-slim` + `dpkg-deb`,
   `fedora:39` + `fpm`, or `ubuntu:22.04` + `appimagetool`) builds the package.

**Launch architecture:** Electron (main process, Node.js) starts the Python backend
as a child process (`python -m app.launcher --no-gui` → uvicorn on `:8000`),
waits for it to be ready by polling `/api/health`, then opens a **native
Chromium GUI window** (BrowserWindow 1280×820) at the URL `http://127.0.0.1:8000`.
uvicorn itself serves both the API and the SPA via a `StaticFiles(html=True)` fallback
(`main.py:96`) — Caddy is not needed in the desktop version. When the window is closed, Electron
kills the child Python process. The systemd service is started with the `--no-gui` flag
(uvicorn only, without Electron).

### Usage

```bash
# Single format:
./packaging/scripts/build-deb.sh        # → dist-packages/*.deb
./packaging/scripts/build-rpm.sh        # → dist-packages/*.rpm
./packaging/scripts/build-appimage.sh   # → dist-packages/*.AppImage
./packaging/scripts/build-arch.sh       # → dist-packages/*.pkg.tar.zst (CachyOS/Arch)

# Version (default 0.1.5):
./packaging/scripts/build-deb.sh 0.2.0
VERSION=0.2.0 ./packaging/scripts/build-deb.sh

# All formats at once:
./packaging/scripts/build-all.sh
```

The host script does `docker build` + `docker cp /dist/. dist-packages/`. All
builds share the first two stages via the BuildKit cache — subsequent builds are fast.
Artifacts are placed in `dist-packages/` (in `.gitignore`).

### Package structure

Installing the deb/rpm places files like this:

```
/opt/vipergirls-viewer/
├── python/                      # bundled Python 3.12 + all deps
│   ├── bin/python3.12
│   └── lib/python3.12/...
├── backend/
│   ├── app/                     # FastAPI source
│   ├── static/                  # built React SPA
│   └── run.sh                   # launcher (GUI → Electron, --no-gui → uvicorn)
└── electron/                    # Electron runtime (Chromium + Node.js)
    ├── electron                 # Chromium binary (~170 MB uncompressed)
    ├── *.so, *.dat, *.bin       # Chromium runtime files
    └── resources/app/
        ├── main.js              # Electron main process
        ├── preload.js           # contextBridge (electronAPI IPC bridge)
        └── package.json
/var/lib/vipergirls-viewer/      # DATA_DIR (SQLite + image cache)
/lib/systemd/system/vipergirls-viewer.service
/usr/share/applications/vipergirls-viewer.desktop
/usr/share/icons/hicolor/256x256/apps/vipergirls-viewer.png
```

The AppImage is a squashfs mounted via FUSE; inside, the structure is the same.
`AppRun` sets `PYTHONHOME` + `LD_LIBRARY_PATH` + `VIPERGIRLS_APP_ROOT`
and launches `./electron --no-sandbox`. User data lives in
`$XDG_DATA_HOME/vipergirls-viewer` (per-user, does not require root).

### Windows (cross-compilation from Linux)

Building Windows packages happens **entirely on Linux via Docker** — neither Wine nor
a Windows host is required. `packaging/docker/windows/Dockerfile` has 5 stages:

1. **frontend** (`node:20-slim`) — `npm ci && npm run build` → `dist/`.
2. **backend** (`python:3.12-slim-bookworm`) — downloads the **Windows embeddable
   Python** (`python-3.12.10-embed-amd64.zip`), enables `import site` in
   the `._pth`, and via `pip download --platform win_amd64` installs all dependencies
   (all of them have prebuilt Windows wheels: curl_cffi, Pillow, lxml, etc.).
   `uvicorn[standard]` is replaced with `uvicorn` (uvloop is Linux-only).
3. **electron** (`alpine:3.20`) — downloads **Electron for Windows**
   (`electron-v31.3.1-win32-x64.zip`).
4. **portable** (`ubuntu:22.04`) — assembles the folder + ZIP archive.
5. **installer** (`ubuntu:22.04` + `nsis` from apt) — the native `makensis`
   builds an NSIS `.exe` installer (Start menu + desktop shortcuts,
   uninstaller).

```bash
# Portable ZIP + NSIS installer:
./packaging/scripts/build-windows.sh        # → dist-packages/*win-x64*
```

Artifacts:
- `vipergirls-viewer-0.1.5-win-x64-portable.zip` (~137 MB) — unpack and
  run `electron/electron.exe`.
- `vipergirls-viewer-0.1.5-win-x64-setup.exe` (~98 MB) — NSIS installer.

Portable folder structure:
```
vipergirls-viewer/
├── python/                      # Windows embeddable Python 3.12 + all deps
│   ├── python.exe
│   ├── python312.dll
│   └── Lib/site-packages/...    # fastapi, uvicorn, httpx, curl_cffi, PIL, lxml
├── backend/
│   ├── app/                     # FastAPI source
│   └── static/                  # built React SPA
└── electron/                    # Electron for Windows
    ├── electron.exe
    ├── *.dll, *.dat, *.bin      # Chromium runtime
    └── resources/app/
        ├── main.js              # Electron main process
        ├── preload.js           # contextBridge (electronAPI IPC bridge)
        ├── package.json
        └── icon.png
```

User data: `%APPDATA%\vipergirls-viewer\` (SQLite + image cache).

---

### Installation and running

**deb:**
```bash
sudo apt install ./dist-packages/vipergirls-viewer_*.deb
# postinst will: create a system user, the data directory, and enable the systemd service
# (server-only on :8000). It also adds a .desktop shortcut — launches the GUI window.
# Manual GUI launch: /opt/vipergirls-viewer/backend/run.sh
```

**rpm:** `sudo dnf install dist-packages/vipergirls-viewer-*.rpm` (or `rpm -i`).
Systemd service on :8000 (no GUI); the .desktop shortcut opens the GUI window.

**AppImage** (no installation, per-user): `chmod +x *.AppImage && ./*.AppImage`
— opens an Electron window, data in `$XDG_DATA_HOME/vipergirls-viewer/`.

**Arch / CachyOS:** `sudo pacman -U dist-packages/vipergirls-viewer-*.pkg.tar.zst`.
The `post_install` hook creates a system user, enables the systemd service, and
registers the shortcut. CachyOS is built on the Arch package base (pacman), so the
native `.pkg.tar.zst` installs as a regular local package without AUR.

### Before building

- **Cross-platform is not supported for AppImage/rpm**: build on a Linux host
  (or in a Linux Docker container). deb/rpm/AppImage are all for x86_64 linux.
- A **frontend build** is mandatory: the `node:20-slim` stage runs `npm ci`, so
  `frontend/package-lock.json` must be up to date. If you changed the frontend,
  run `cd frontend && npm install` locally to update the lockfile.
- Artifact sizes: **deb ~108 MB, rpm ~146 MB, AppImage ~148 MB, arch ~108 MB**. The main
  contribution is the Electron runtime (~100 MB Chromium + Node.js) + the Python runtime (~40 MB).
- For deb/rpm, the target system must have the set of system libraries required by Electron
  (libgtk-3, libnss3, libasound2, libgbm1, and others — the packages declare these
  dependencies, apt/dnf will pull them in automatically). AppImage works without
  system deps (only glibc 2.36+ — Debian 12 / Ubuntu 23.04+).
- To change the icon/name, edit `packaging/common/make-icon.py` and `*.desktop`.

---

### Podman instead of Docker

All `Dockerfile`s are compatible with **Podman** (OCI-compatible, daemonless, usually
rootless). For every docker script there is a matching podman script — the shared engine
is factored out into `_common.sh` (function `build_pkg <runner> <format>`), so the
behavior is identical and only the runner differs:

| Docker | Podman |
|---|---|
| `build-deb.sh` | `build-deb-podman.sh` |
| `build-rpm.sh` | `build-rpm-podman.sh` |
| `build-appimage.sh` | `build-appimage-podman.sh` |
| `build-windows.sh` | `build-windows-podman.sh` |
| `build-arch.sh` | `build-arch-podman.sh` |
| `build-all.sh` | `build-all-podman.sh` |

```bash
# All formats at once:
./packaging/scripts/build-all-podman.sh

# Or a single format (version as argument or via VERSION=):
./packaging/scripts/build-deb-podman.sh 0.1.5
```

Layers are cached between builds (Buildah backend) — subsequent builds are as fast as
with Docker. The commands under the hood (`build` / `create` / `cp`, the `--target
installer` flag in the windows build) are fully supported by podman.

**A no-edit alternative** — a translating wrapper, if you prefer the original
docker scripts:

```bash
# Option A — system shim (Debian/Fedora): the podman-docker package installs
# /usr/bin/docker → podman, docker scripts work as-is.
sudo apt install podman podman-docker        # or: sudo dnf install podman-docker

# Option B — alias in the current shell:
alias docker=podman
./packaging/scripts/build-all.sh
```

Manual build (the same thing `build-deb-podman.sh` does):

```bash
podman build -f packaging/docker/deb/Dockerfile --build-arg VERSION=0.1.5 \
    -t viper-viewer-deb .
CID=$(podman create viper-viewer-deb)
podman cp "$CID:/dist/." dist-packages/
podman rm "$CID"
```

**Server stack.** Instead of `docker compose`:

```bash
podman compose up -d --build   # → http://localhost:8888
```

`podman compose` (Podman ≥ 4.7) delegates to `docker-compose` — it must be
present in the PATH. The old standalone `podman-compose` also works, but the built-in
subcommand is preferred.

**Rootless / SELinux caveats:**

- **SELinux** (Fedora/RHEL/CentOS): binding `./data:/data` without a label forbids
  the container from writing to `viper.db` and `cache/`. Add the `:Z` suffix locally
  (do not commit it — on Docker Desktop / Ubuntu without SELinux it is unnecessary and
  can interfere): `volumes: ["./data:/data:Z"]`.
- **Ports < 1024**: rootless podman does not bind privileged host ports
  without the sysctl `net.ipv4.ip_unprivileged_port_start=80`. The current mapping
  `8888:80` (>1024 on the host) has no issues — keep this in mind when changing the port.
- **Volume permissions**: if files in `./data` are created by a foreign uid (visible as
  `nobody`/a foreign owner), run with `--userns=keep-id` (or
  `PODMAN_USERNS=keep-id`) so that root inside the container maps to the
  invoking host user.
- **systemd service via Quadlet** (Podman ≥ 4.4) — a native alternative to
  `docker compose` for auto-start. Place `viper-viewer.container` in
  `~/.config/containers/systemd/` (rootless, user-unit) or
  `/etc/containers/systemd/` (system):

  ```ini
  [Container]
  Image=localhost/viper-viewer
  ContainerName=viper-viewer
  PublishPort=8888:80
  Volume=%h/data:/data:Z
  Environment=VIPER_REQUEST_LIMIT=2
  Environment=VIPER_CACHE_LIMIT_GB=0
  [Install]
  WantedBy=default.target
  ```

  Then `systemctl --user daemon-reload && systemctl --user start
  viper-viewer` — Quadlet will generate the unit and start the container itself. The image
  referenced by `Image=` must exist locally (`podman build -t localhost/viper-viewer
  .`); after a rebuild — `systemctl --user restart viper-viewer`.

---

## 2. Alternative: PyInstaller + Tauri/Electron (manual)

> The approaches below are **not implemented** in the repository — this is a manual
> alternative in case the Docker build from section 1 does not suit you. For Windows/macOS
> Tauri is the only way to get a native `.exe`/`.dmg`.

### Preparation: backend into a standalone binary (PyInstaller)

Regardless of the desktop shell, the Python backend must be turned into a single
executable file so that the end user does not need Python.

### Steps

```bash
# Install PyInstaller
pip install pyinstaller

# Build a single-file server (in the backend/ directory)
cd backend

pyinstaller \
  --onefile \
  --name viper-backend \
  --add-data "app:app" \
  --hidden-import aiosqlite \
  --hidden-import curl_cffi._wrapper \
  --hidden-import PIL._tkinter_finder \
  app/main.py
```

This produces `dist/viper-backend` (Linux/macOS) or `dist/viper-backend.exe` (Windows).
This binary launches uvicorn on the specified port:

```bash
DATA_DIR=./data VIPER_FORUM_BASE_URL=https://viper.to ./viper-backend
# → uvicorn on :8000
```

### Caveats

- `curl_cffi` pulls in native libraries (libcurl-impersonate). On Windows you may
  need `--collect-all curl_cffi`.
- `lxml` is also native; PyInstaller usually finds it on its own, but on errors
  add `--collect-all lxml`.
- Binary size ~60–90 MB (FastAPI + httpx + curl_cffi + Pillow + lxml).
- Caddy is **not needed** in the desktop variant — uvicorn can serve static assets directly
  via `StaticFiles` (see the variant in `main.py`, you need to mount `dist/`).
  Alternatively, use Tauri/Electron to serve the static assets.

### Simplification: remove Caddy

In the desktop version it is simpler to remove Caddy and serve the SPA directly from FastAPI.
This fallback is already built into `app/main.py` — if the `backend/static/` directory
exists, uvicorn mounts it via `StaticFiles(html=True)` at the root
(see `main.py`, after the routers are connected):

```python
_static = Path(__file__).resolve().parent.parent / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
```

It is enough to drop the built `frontend/dist` into `backend/static/` — and all
traffic (API + SPA) goes through a single port (uvicorn).

---

### Desktop shell (Tauri)

**Tauri** creates native applications from a web frontend using the system
webview (no embedded Chromium → small size). Ideal for our SPA.

Principle:
- React build (`frontend/dist`) → the frontend of the Tauri application.
- PyInstaller backend binary → a **sidecar** process (started on launch,
  killed on close).
- Tauri opens a webview at `http://localhost:<port>`.

### Initializing a Tauri project

```bash
# Install Rust (once)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Initialize Tauri at the project root
npm create tauri-app@latest
# Choose: manage frontend → point to frontend/ , template → vanilla-ts
```

The structure will appear in `src-tauri/`. Configure `tauri.conf.json`:

```jsonc
{
  "build": {
    "beforeBuildCommand": "cd ../frontend && npm run build",
    "frontendDist": "../frontend/dist",
    "beforeDevCommand": "cd ../frontend && npm run dev",
    "devUrl": "http://localhost:5173"
  },
  "tauri": {
    "bundle": {
      "active": true,
      "targets": "all",
      "icon": ["icons/icon.png"]
    }
  }
}
```

### Running the backend as a sidecar

1. Place the PyInstaller binary in `src-tauri/binaries/`.
2. Declare the sidecar in `tauri.conf.json`:

```jsonc
"bundle": {
  "externalBin": ["binaries/viper-backend"]
}
```

3. In the Rust code (`src-tauri/src/main.rs`) start the sidecar on launch:

```rust
use tauri::api::process::Command;

fn main() {
    tauri::Builder::default()
        .setup(|_app| {
            // Start the backend in the background
            let _child = Command::new_sidecar("viper-backend")
                .expect("failed to create sidecar")
                .spawn()
                .expect("failed to spawn sidecar");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running application");
    // When the window is closed, the sidecar will terminate automatically (managed child)
}
```

4. The frontend loads directly at `http://localhost:8000` (or via the Tauri webview
   with a redirect). The simplest option: `frontendDist` points to
   a minimal `index.html` that redirects to `localhost:8000`.
   Alternatively — serve the static assets from the backend (see above) and the webview loads `localhost:8000`.

### Windows (.exe / .msi)

```bash
# On Windows (or cross-compilation is not supported by Tauri — a Windows host is needed)
cd src-tauri
cargo tauri build
```

Result in `src-tauri/target/release/bundle/`:
- **NSIS installer**: `nsis/*.exe` — a classic installer.
- **MSI**: `msi/*.msi` — for enterprise deployment.

Build machine requirements: Visual Studio Build Tools (MSVC), WebView2
(preinstalled on Windows 10/11).

### Linux (.deb / .rpm)

```bash
# On Linux
cd src-tauri
cargo tauri build
```

Result:
- **.deb**: `deb/*.deb` — for Debian/Ubuntu.
- **.rpm**: `rpm/*.rpm` — for Fedora/RHEL/openSUSE.
- **.AppImage**: `appimage/*.AppImage` — portable format (bonus).

Requirements: `sudo apt install -y libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev patchelf`.

### macOS (.dmg / .app)

```bash
# On macOS
cd src-tauri
cargo tauri build
```

Result:
- **.app**: `macos/*.app` — application bundle.
- **.dmg**: `dmg/*.dmg` — disk image for distribution.

Requirements: Xcode Command Line Tools (`xcode-select --install`).
For distribution outside the App Store, an **ad-hoc signature** or an Apple Developer ID is required:
```bash
cargo tauri build --target universal-apple-darwin  # Universal binary (Intel + ARM)
```

> ⚠️ Tauri **does not support cross-compilation**. Each format must be built
> on its native OS (or in CI — GitHub Actions with an OS matrix).

---

### Alternative: Electron

If Rust/Tauri is undesirable, Electron is a proven alternative (Chromium +
Node.js). The bundle is larger (~150 MB), but the ecosystem is richer.

```bash
npm install --save-dev electron electron-builder
```

`main.cjs` (Electron main process):

```javascript
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

let backendProcess;

function createWindow() {
  const win = new BrowserWindow({ width: 1280, height: 800 });
  win.loadURL("http://localhost:8000");
}

app.whenReady().then(() => {
  // Launch the PyInstaller binary
  const bin = path.join(
    process.platform === "win32" ? "viper-backend.exe" : "viper-backend"
  );
  backendProcess = spawn(bin, [], {
    env: { ...process.env, DATA_DIR: app.getPath("userData") },
  });

  // Wait a second for uvicorn to start
  setTimeout(createWindow, 1500);
});

app.on("window-all-closed", () => {
  if (backendProcess) backendProcess.kill();
  app.quit();
});
```

`package.json` (add):

```json
{
  "build": {
    "appId": "com.example.vipergirls-viewer",
    "files": ["main.cjs", "binaries/**"],
    "extraResources": [{ "from": "binaries/", "to": "binaries/" }],
    "win": { "target": ["nsis", "portable"] },
    "linux": { "target": ["deb", "rpm", "AppImage"] },
    "mac": { "target": ["dmg"] }
  }
}
```

Build:

```bash
npx electron-builder --win   # .exe (NSIS) + portable
npx electron-builder --linux # .deb, .rpm, .AppImage
npx electron-builder --mac   # .dmg
```

---

### Publishing the frontend to npm

Currently the frontend is a private app (`"private": true` in `package.json`).
Publishing to npm makes sense if:

**Option A — publish as a ready build (deployable package):**

```bash
cd frontend
# In package.json, change:
#   "private": false
#   "name": "vipergirls-viewer-ui"
npm run build
npm publish --access public
```

After installing with `npm install vipergirls-viewer-ui` the user gets `dist/`
to be served by any static server.

**Option B — publish as a component library** (ThreadCard, Sidebar,
useViewMode, useImageRetry, etc.) — requires refactoring: extract components
into a separate entry point, configure `exports` in `package.json`, and build via
`vite build --lib` or `tsup`.

```json
{
  "name": "vipergirls-ui-kit",
  "main": "dist/index.js",
  "module": "dist/index.mjs",
  "types": "dist/index.d.ts",
  "exports": {
    ".": { "import": "./dist/index.mjs", "require": "./dist/index.js" }
  },
  "files": ["dist"]
}
```

**Option C — GitHub Packages** (instead of public npm):
```bash
# In package.json: "publishConfig": { "registry": "https://npm.pkg.github.com" }
npm publish
```

> ⚠️ The frontend on its own is useless without the backend — it only makes sense
> to publish it as part of documentation/template, or together with instructions
> for running Docker (see `AGENTS.md`).

---

## 3. Summary table of tools

| Format       | Tool                | Build OS          | Size      |
|--------------|---------------------|--------------------|-----------|
| `.deb`       | Docker + dpkg-deb   | Linux (Docker)     | ~108 MB   |
| `.rpm`       | Docker + fpm        | Linux (Docker)     | ~146 MB   |
| `.AppImage`  | Docker + appimagetool | Linux (Docker)  | ~148 MB   |
| `.pkg.tar.zst` (Arch/CachyOS) | Docker + makepkg | Linux (Docker) | ~108 MB |
| `.zip` (Win) | Docker + pip download | Linux (Docker) | ~137 MB   |
| `.exe` (Win) | Docker + NSIS       | Linux (Docker)     | ~98 MB    |
| PyInstaller bundle (macOS) | GitHub Actions + PyInstaller | macOS (CI: arm64) | ~60–90 MB |
| Docker image | docker compose      | Any                | ~300 MB   |

### Recommended path

- **Linux (deb/rpm/AppImage, Arch/CachyOS)** — section 1 (ready-made Docker scripts in `packaging/`).
- **Windows (.zip/.exe)** — section 1 (Docker cross-compilation from Linux).
- **macOS** — PyInstaller bundle via the `.github/workflows/build-macos.yml` CI
  workflow (`macos-14` arm64; Intel x64 was dropped — GitHub is deprecating
  `macos-13` runners), or Tauri + PyInstaller sidecar (section 2, manually).
- **Server/web deployment** — Docker (`docker compose up -d --build`, see `AGENTS.md`).

### CI/CD (GitHub Actions — autobuild of Linux packages)

```yaml
# .github/workflows/build-linux.yml
jobs:
  build-packages:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ./packaging/scripts/build-all.sh 0.${{ github.run_number }}.0
      - uses: actions/upload-artifact@v4
        with:
          name: linux-packages
          path: dist-packages/*
```

### CI/CD — macOS (PyInstaller smoke test + bundle)

A **separate** workflow, `.github/workflows/build-macos.yml`, runs on every push
and builds the app on `macos-14` (Apple Silicon arm64). Intel x64 (`macos-13`)
was dropped because GitHub is deprecating those runners and they no longer
allocate in reasonable time. It is independent of the Docker/podman native
packaging from section 1 (which is cross-compiled from Linux and covers
deb/rpm/AppImage/arch + Windows) — macOS has no native packaging path in
Docker, so the GitHub Actions workflow is the supported route for Apple Silicon.

What the workflow does:

1. **Frontend** — `npm ci && npm run build` → `frontend/dist/`.
2. **Backend deps** — installs `backend/requirements.txt`.
3. **Smoke test** — starts the backend (uvicorn) and polls `GET /api/health`
   until it responds.
4. **PyInstaller bundle** (best-effort, `continue-on-error`) — bundles
   `vipergirls-backend` via CLI flags. No `.spec` file exists yet, so the
   `--add-data` / `--hidden-import` flags are passed inline.
5. **Artifacts** — uploads `frontend/dist/` and `backend/dist/`.

```yaml
# .github/workflows/build-macos.yml
on: [push]
jobs:
  build:
    strategy:
      fail-fast: false
      matrix:
        os: [macos-14]   # arm64 (Apple Silicon)
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: 20 }
      - run: cd frontend && npm ci && npm run build
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -r backend/requirements.txt
      - name: Smoke test backend
        run: |
          cd backend
          uvicorn app.main:app --port 8000 &
          for i in $(seq 1 30); do
            curl -sf http://127.0.0.1:8000/api/health && break
            sleep 1
          done
      - run: pip install pyinstaller
      - name: PyInstaller bundle (best-effort)
        continue-on-error: true
        run: |
          cd backend
          pyinstaller --onefile --name vipergirls-backend \
            --add-data "app:app" \
            --hidden-import aiosqlite \
            --hidden-import curl_cffi._wrapper \
            app/main.py
      - uses: actions/upload-artifact@v4
        with: { name: macos-${{ matrix.os }}-frontend, path: frontend/dist/ }
      - uses: actions/upload-artifact@v4
        with: { name: macos-${{ matrix.os }}-backend, path: backend/dist/ }
```
