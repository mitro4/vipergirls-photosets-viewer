# Упаковка и распространение приложения

Текущая архитектура — **веб-приложение**: Python/FastAPI backend (парсинг форума,
проксирование изображений, сборка ZIP, постоянная очередь загрузок и скачивание в папки) +
React SPA + Caddy (отдаёт статику и проксирует API). Постоянная очередь загрузок живёт в
`app/services/download_queue.py` (сервис) и `app/api/download_queue.py` (роутер). Это описано
в `AGENTS.md`.

Для десктоп-дистрибутивов нужно упаковать **и фронтенд, и бэкенд** в один
запускаемый bundle. Ниже — практические пути для каждого формата.

---

## Содержание

1. [Сборка через Docker (рабочий способ — deb / rpm / AppImage / Windows)](#1-сборка-через-docker-рабочий-способ--deb--rpm--appimage--windows)
   - [Как это работает](#как-это-работает)
   - [Использование](#использование)
   - [Структура пакетов](#структура-пакетов)
   - [Установка и запуск](#установка-и-запуск)
   - [Перед сборкой](#перед-сборкой)
   - [Podman вместо Docker](#podman-вместо-docker)
2. [Альтернатива: PyInstaller + Tauri/Electron (вручную)](#2-альтернатива-pyinstaller--tauielectron-вручную)
   - [Подготовка: бэкенд в standalone-бинарник (PyInstaller)](#подготовка-бэкенд-в-standalone-бинарник-pyinstaller)
   - [Десктоп-оболочка (Tauri)](#десктоп-оболочка-tauri)
   - [Альтернатива: Electron](#альтернатива-electron)
   - [Публикация фронтенда в npm](#публикация-фронтенда-в-npm)
3. [Сводная таблица инструментов](#3-сводная-таблица-инструментов)

---

## 1. Сборка через Docker (рабочий способ — deb / rpm / AppImage / Windows)

В каталоге `packaging/` лежат готовые скрипты и Dockerfile'ы, которые собирают
нативные пакеты **воспроизводимо в Docker** — без установки локальных
инструментов (dpkg-deb / fpm / appimagetool). Нужен только Docker на хосте.

### Как это работает

Каждый формат (`deb`, `rpm`, `appimage`) имеет собственный Dockerfile с
четырьмя этапами:

1. **frontend** (`node:20-slim`) — `npm ci && npm run build` → `dist/`.
2. **backend** (`python:3.12-slim-bookworm`) — устанавливает все зависимости из
   `backend/requirements.txt` в системный Python, затем копирует **весь**
   `/usr/local/` (интерпретатор + stdlib + site-packages + libpython) в payload.
   Кеши (`__pycache__`) и заголовки (`include/`) вырезаются. Системные .so
   (libssl, libcrypto, libfontconfig, ...) **не бандлятся** — они берутся из
   целевой ОС ( pip-пакеты включают свои нативные deps в wheels).
3. **electron** (`alpine:3.20`) — скачивает готовый Electron runtime
   (Chromium + Node.js, ~100 МБ zip) с GitHub releases и распаковывает его.
4. **package** — формат-специфичный образ (`debian:bookworm-slim` + `dpkg-deb`,
   `fedora:39` + `fpm`, или `ubuntu:22.04` + `appimagetool`) собирает пакет.

**Архитектура запуска:** Electron (главный процесс, Node.js) запускает Python-бэкенд
как дочерний процесс (`python -m app.launcher --no-gui` → uvicorn на `:8000`),
дожидается готовности через polling `/api/health`, затем открывает **нативное
GUI-окно** Chromium (BrowserWindow 1280×820) с URL `http://127.0.0.1:8000`.
uvicorn сам отдаёт и API, и SPA через `StaticFiles(html=True)` fallback
(`main.py:96`) — Caddy в десктоп-версии не нужен. При закрытии окна Electron
убивает дочерний Python-процесс. systemd-сервис запускается с флагом `--no-gui`
(только uvicorn, без Electron).

### Использование

```bash
# Один формат:
./packaging/scripts/build-deb.sh        # → dist-packages/*.deb
./packaging/scripts/build-rpm.sh        # → dist-packages/*.rpm
./packaging/scripts/build-appimage.sh   # → dist-packages/*.AppImage
./packaging/scripts/build-arch.sh       # → dist-packages/*.pkg.tar.zst (CachyOS/Arch)

# Версия (по умолчанию 0.1.5):
./packaging/scripts/build-deb.sh 0.2.0
VERSION=0.2.0 ./packaging/scripts/build-deb.sh

# Все форматы сразу:
./packaging/scripts/build-all.sh
```

Хост-скрипт делает `docker build` + `docker cp /dist/. dist-packages/`. Все
сборки шарят первые два этапа через BuildKit-кеш — повторные сборки быстрые.
Артефакты кладутся в `dist-packages/` (в `.gitignore`).

### Структура пакетов

Установка deb/rpm кладёт файлы так:

```
/opt/vipergirls-viewer/
├── python/                      # bundled Python 3.12 + все deps
│   ├── bin/python3.12
│   └── lib/python3.12/...
├── backend/
│   ├── app/                     # FastAPI source
│   ├── static/                  # собранный React SPA
│   └── run.sh                   # launcher (GUI → Electron, --no-gui → uvicorn)
└── electron/                    # Electron runtime (Chromium + Node.js)
    ├── electron                 # Chromium binary (~170 МБ uncompressed)
    ├── *.so, *.dat, *.bin       # Chromium runtime files
    └── resources/app/
        ├── main.js              # Electron main process
        ├── preload.js           # contextBridge (electronAPI IPC bridge)
        └── package.json
/var/lib/vipergirls-viewer/      # DATA_DIR (SQLite + кеш картинок)
/lib/systemd/system/vipergirls-viewer.service
/usr/share/applications/vipergirls-viewer.desktop
/usr/share/icons/hicolor/256x256/apps/vipergirls-viewer.png
```

AppImage — это squashfs, смонтированный через FUSE; внутри та же структура.
`AppRun` выставляет `PYTHONHOME` + `LD_LIBRARY_PATH` + `VIPERGIRLS_APP_ROOT`
и запускает `./electron --no-sandbox`. Данные пользователя — в
`$XDG_DATA_HOME/vipergirls-viewer` (per-user, не требует root).

### Windows (кросс-компиляция из Linux)

Сборка Windows-пакетов идёт **полностью на Linux через Docker** — ни Wine, ни
Windows-хост не требуются. `packaging/docker/windows/Dockerfile` имеет 5 этапов:

1. **frontend** (`node:20-slim`) — `npm ci && npm run build` → `dist/`.
2. **backend** (`python:3.12-slim-bookworm`) — скачивает **Windows embeddable
   Python** (`python-3.12.10-embed-amd64.zip`), активирует `import site` в
   `._pth`, и через `pip download --platform win_amd64` ставит все зависимости
   (у всех есть prebuilt Windows wheels: curl_cffi, Pillow, lxml, etc.).
   `uvicorn[standard]` заменяется на `uvicorn` (uvloop — Linux-only).
3. **electron** (`alpine:3.20`) — скачивает **Electron для Windows**
   (`electron-v31.3.1-win32-x64.zip`).
4. **portable** (`ubuntu:22.04`) — собирает папку + ZIP-архив.
5. **installer** (`ubuntu:22.04` + `nsis` из apt) — нативный `makensis`
   собирает NSIS-установщик `.exe` (ярлыки в меню Пуск + рабочий стол,
   uninstaller).

```bash
# Portable ZIP + NSIS installer:
./packaging/scripts/build-windows.sh        # → dist-packages/*win-x64*
```

Артефакты:
- `vipergirls-viewer-0.1.5-win-x64-portable.zip` (~137 МБ) — распаковать и
  запустить `electron/electron.exe`.
- `vipergirls-viewer-0.1.5-win-x64-setup.exe` (~98 МБ) — NSIS-установщик.

Структура портативной папки:
```
vipergirls-viewer/
├── python/                      # Windows embeddable Python 3.12 + все deps
│   ├── python.exe
│   ├── python312.dll
│   └── Lib/site-packages/...    # fastapi, uvicorn, httpx, curl_cffi, PIL, lxml
├── backend/
│   ├── app/                     # FastAPI source
│   └── static/                  # собранный React SPA
└── electron/                    # Electron для Windows
    ├── electron.exe
    ├── *.dll, *.dat, *.bin      # Chromium runtime
    └── resources/app/
        ├── main.js              # Electron main process
        ├── preload.js           # contextBridge (electronAPI IPC bridge)
        ├── package.json
        └── icon.png
```

Данные пользователя: `%APPDATA%\vipergirls-viewer\` (SQLite + кеш картинок).

---

### Установка и запуск

**deb:**
```bash
sudo apt install ./dist-packages/vipergirls-viewer_*.deb
# postinst сам: создаст системного юзера, data-каталог, включит systemd-сервис
# (server-only на :8000). Также добавит .desktop-ярлык — запускает GUI-окно.
# Ручной запуск GUI: /opt/vipergirls-viewer/backend/run.sh
```

**rpm:** `sudo dnf install dist-packages/vipergirls-viewer-*.rpm` (или `rpm -i`).
Systemd-сервис на :8000 (без GUI); .desktop-ярлык открывает GUI-окно.

**AppImage** (без установки, per-user): `chmod +x *.AppImage && ./*.AppImage`
— открывает Electron-окно, данные в `$XDG_DATA_HOME/vipergirls-viewer/`.

**Arch / CachyOS:** `sudo pacman -U dist-packages/vipergirls-viewer-*.pkg.tar.zst`.
Хук `post_install` создаёт системного пользователя, включает systemd-сервис и
регистрирует ярлык. CachyOS собран на пакетной базе Arch (pacman), поэтому
нативный `.pkg.tar.zst` ставится как обычный локальный пакет без AUR.

### Перед сборкой

- **Cross-platform не поддерживается для AppImage/rpm**: собирайте на Linux-хосте
  (или в Linux Docker). deb/rpm/AppImage — все для x86_64 linux.
- Обязателен **frontend build**: этап `node:20-slim` запускает `npm ci`, поэтому
  `frontend/package-lock.json` должен быть актуален. Если меняли фронтенд —
  `cd frontend && npm install` локально для обновления lock-файла.
- Размер артефактов: **deb ~108 МБ, rpm ~146 МБ, AppImage ~148 МБ, arch ~108 МБ**. Основной
  вклад — Electron runtime (~100 МБ Chromium + Node.js) + Python runtime (~40 МБ).
- Для deb/rpm на target-системе должен быть установлен набор системных библиотек
  для Electron (libgtk-3, libnss3, libasound2, libgbm1, и др. — пакеты
  декларируют зависимости, apt/dnf подтянет автоматически). AppImage работает
  без системных deps (только glibc 2.36+ — Debian 12 / Ubuntu 23.04+).
- Для смены иконки/имени правьте `packaging/common/make-icon.py` и `*.desktop`.

---

### Podman вместо Docker

Все `Dockerfile` совместимы с **Podman** (OCI-совместимый, daemonless, обычно
rootless). Для каждого docker-скрипта есть парный podman-скрипт — общий движок
вынесен в `_common.sh` (функция `build_pkg <runner> <format>`), поэтому
поведение идентично, отличается только раннером:

| Docker | Podman |
|---|---|
| `build-deb.sh` | `build-deb-podman.sh` |
| `build-rpm.sh` | `build-rpm-podman.sh` |
| `build-appimage.sh` | `build-appimage-podman.sh` |
| `build-windows.sh` | `build-windows-podman.sh` |
| `build-arch.sh` | `build-arch-podman.sh` |
| `build-all.sh` | `build-all-podman.sh` |

```bash
# Все форматы сразу:
./packaging/scripts/build-all-podman.sh

# Или один формат (версия аргументом или через VERSION=):
./packaging/scripts/build-deb-podman.sh 0.1.5
```

Слои кешируются между сборками (бэкенд Buildah) — повторные сборки быстрые, как
в Docker. Команды под капотом (`build` / `create` / `cp`, флаг `--target
installer` в windows-сборке) полностью поддерживаются podman.

**Альтернатива без правки** — транслирующая обёртка, если предпочитаете
оригинальные docker-скрипты:

```bash
# Вариант A — системный shim (Debian/Fedora): пакет podman-docker ставит
# /usr/bin/docker → podman, docker-скрипты работают как есть.
sudo apt install podman podman-docker        # или: sudo dnf install podman-docker

# Вариант B — алиас в текущем shell:
alias docker=podman
./packaging/scripts/build-all.sh
```

Ручная сборка (то же, что делает `build-deb-podman.sh`):

```bash
podman build -f packaging/docker/deb/Dockerfile --build-arg VERSION=0.1.5 \
    -t viper-viewer-deb .
CID=$(podman create viper-viewer-deb)
podman cp "$CID:/dist/." dist-packages/
podman rm "$CID"
```

**Серверный стек.** Вместо `docker compose`:

```bash
podman compose up -d --build   # → http://localhost:8888
```

`podman compose` (Podman ≥ 4.7) делегирует в `docker-compose` — он должен
стоять в PATH. Старый отдельный `podman-compose` тоже работает, но встроенный
subcommand предпочтительнее.

**Подводные камни rootless / SELinux:**

- **SELinux** (Fedora/RHEL/CentOS): bind `./data:/data` без метки запрещает
  контейнеру писать в `viper.db` и `cache/`. Добавьте суффикс `:Z` локально
  (не коммитьте — на Docker Desktop / Ubuntu без SELinux он не нужен и может
  мешать): `volumes: ["./data:/data:Z"]`.
- **Порты < 1024**: rootless podman не биндит привилегированные хост-порты
  без sysctl `net.ipv4.ip_unprivileged_port_start=80`. Текущий маппинг
  `8888:80` (>1024 на хосте) проблем не имеет — учитывайте это при смене порта.
- **Права на томе**: если файлы в `./data` создаются от чужого uid (видно как
  `nobody`/чужой владелец), запустите с `--userns=keep-id` (или
  `PODMAN_USERNS=keep-id`), чтобы root внутри контейнера маппился на
  вызывающего юзера хоста.
- **systemd-сервис через Quadlet** (Podman ≥ 4.4) — нативная альтернатива
  `docker compose` для автозапуска. Положите `viper-viewer.container` в
  `~/.config/containers/systemd/` (rootless, user-unit) или
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

  Затем `systemctl --user daemon-reload && systemctl --user start
  viper-viewer` — Quadlet сам сгенерирует unit и запустит контейнер. Образ по
  `Image=` должен существовать локально (`podman build -t localhost/viper-viewer
  .`); после пересборки — `systemctl --user restart viper-viewer`.

---

## 2. Альтернатива: PyInstaller + Tauri/Electron (вручную)

> Способы ниже **не реализованы** в репозитории — это ручная альтернатива, если
> Docker-сборка из раздела 1 не подходит. Для Windows/macOS Tauri — единственный
> путь получить нативный `.exe`/`.dmg`.

### Подготовка: бэкенд в standalone-бинарник (PyInstaller)

Независимо от десктоп-оболочки, Python-бэкенд нужно превратить в один
запускаемый файл, чтобы конечному пользователю не нужен был Python.

### Шаги

```bash
# Установка PyInstaller
pip install pyinstaller

# Сборка однофайлного сервера (в директории backend/)
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

Получится `dist/viper-backend` (Linux/macOS) или `dist/viper-backend.exe` (Windows).
Этот бинарник запускает uvicorn на указанном порту:

```bash
DATA_DIR=./data VIPER_FORUM_BASE_URL=https://viper.to ./viper-backend
# → uvicorn на :8000
```

### Подводные камни

- `curl_cffi` тащит нативные библиотеки (libcurl-impersonate). На Windows может
  потребоваться `--collect-all curl_cffi`.
- `lxml` тоже нативный; PyInstaller обычно находит его сам, но при ошибках
  добавьте `--collect-all lxml`.
- Размер бинарника ~60–90 МБ (FastAPI + httpx + curl_cffi + Pillow + lxml).
- Caddy в десктоп-варианте **не нужен** — uvicorn может отдавать статику напрямую
  через `StaticFiles` (см. вариант в `main.py`, нужно примонтировать `dist/`).
  Либо используйте Tauri/Electron для раздачи статики.

### Упрощение: убрать Caddy

В десктоп-версии проще убрать Caddy и отдавать SPA напрямую из FastAPI.
Этот fallback уже встроен в `app/main.py` — если каталог `backend/static/`
существует, uvicorn монтирует его через `StaticFiles(html=True)` на корень
(см. `main.py`, после подключения роутеров):

```python
_static = Path(__file__).resolve().parent.parent / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
```

Достаточно сложить собранный `frontend/dist` в `backend/static/` — и весь
трафик (API + SPA) идёт через один порт (uvicorn).

---

### Десктоп-оболочка (Tauri)

**Tauri** создаёт нативные приложения из веб-фронтенда, используя системный
webview (никакого встроенного Chromium → малый размер). Идеально для нашей SPA.

Принцип:
- React-сборка (`frontend/dist`) → фронтенд Tauri-приложения.
- PyInstaller-бинарник бэкенда → **sidecar**-процесс (запускается при старте,
  убивается при закрытии).
- Tauri открывает webview на `http://localhost:<port>`.

### Инициализация Tauri-проекта

```bash
# Установить Rust (один раз)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# В корне проекта инициализировать Tauri
npm create tauri-app@latest
# Выбрать: manage frontend → указать frontend/ , template → vanilla-ts
```

Структура появится в `src-tauri/`. Настройте `tauri.conf.json`:

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

### Запуск бэкенда как sidecar

1. Положите PyInstaller-бинарник в `src-tauri/binaries/`.
2. В `tauri.conf.json` объявите sidecar:

```jsonc
"bundle": {
  "externalBin": ["binaries/viper-backend"]
}
```

3. В Rust-коде (`src-tauri/src/main.rs`) запускайте sidecar при старте:

```rust
use tauri::api::process::Command;

fn main() {
    tauri::Builder::default()
        .setup(|_app| {
            // Запускаем бэкенд в фоне
            let _child = Command::new_sidecar("viper-backend")
                .expect("failed to create sidecar")
                .spawn()
                .expect("failed to spawn sidecar");
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running application");
    // При закрытии окна sidecar завершится автоматически (managed child)
}
```

4. Фронтенд грузится сразу на `http://localhost:8000` (или через Tauri-webview
   с перенаправлением). Простейший вариант: `frontendDist` указывает на
   минимальный `index.html`, который редиректит на `localhost:8000`.
   Либо — отдавайте статику из бэкенда (см. выше) и webview грузит `localhost:8000`.

### Windows (.exe / .msi)

```bash
# На Windows (или кросс-компиляция не поддерживается Tauri — нужен Windows-хост)
cd src-tauri
cargo tauri build
```

Результат в `src-tauri/target/release/bundle/`:
- **NSIS installer**: `nsis/*.exe` — классический установщик.
- **MSI**: `msi/*.msi` — для корпоративного развёртывания.

Требования на машине сборки: Visual Studio Build Tools (MSVC), WebView2
(предустановлен на Windows 10/11).

### Linux (.deb / .rpm)

```bash
# На Linux
cd src-tauri
cargo tauri build
```

Результат:
- **.deb**: `deb/*.deb` — для Debian/Ubuntu.
- **.rpm**: `rpm/*.rpm` — для Fedora/RHEL/openSUSE.
- **.AppImage**: `appimage/*.AppImage` — портативный формат (бонус).

Требования: `sudo apt install -y libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev patchelf`.

### macOS (.dmg / .app)

```bash
# На macOS
cd src-tauri
cargo tauri build
```

Результат:
- **.app**: `macos/*.app` — bundle приложения.
- **.dmg**: `dmg/*.dmg` — образ диска для распространения.

Требования: Xcode Command Line Tools (`xcode-select --install`).
Для распространения вне App Store нужна **ad-hoc подпись** или Apple Developer ID:
```bash
cargo tauri build --target universal-apple-darwin  # Universal binary (Intel + ARM)
```

> ⚠️ Tauri **не поддерживает кросс-компиляцию**. Каждый формат нужно собирать
> на нативной ОС (или в CI — GitHub Actions с матрицей ОС).

---

### Альтернатива: Electron

Если Rust/Tauri нежелателен, Electron — проверенная альтернатива (Chromium +
Node.js). Размер bundle больше (~150 МБ), но экосистема богаче.

```bash
npm install --save-dev electron electron-builder
```

`main.cjs` (главный процесс Electron):

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
  // Запускаем PyInstaller-бинарник
  const bin = path.join(
    process.platform === "win32" ? "viper-backend.exe" : "viper-backend"
  );
  backendProcess = spawn(bin, [], {
    env: { ...process.env, DATA_DIR: app.getPath("userData") },
  });

  // Ждём секунду, чтобы uvicorn стартовал
  setTimeout(createWindow, 1500);
});

app.on("window-all-closed", () => {
  if (backendProcess) backendProcess.kill();
  app.quit();
});
```

`package.json` (добавить):

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

Сборка:

```bash
npx electron-builder --win   # .exe (NSIS) + portable
npx electron-builder --linux # .deb, .rpm, .AppImage
npx electron-builder --mac   # .dmg
```

---

### Публикация фронтенда в npm

Сейчас фронтенд — приватное приложение (`"private": true` в `package.json`).
Публикация в npm имеет смысл, если:

**Вариант A — опубликовать как готовую сборку (deployable package):**

```bash
cd frontend
# Изменить в package.json:
#   "private": false
#   "name": "vipergirls-viewer-ui"
npm run build
npm publish --access public
```

После установки `npm install vipergirls-viewer-ui` пользователь получит `dist/`
для отдачи любым статическим сервером.

**Вариант B — опубликовать как библиотеку компонентов** (ThreadCard, Sidebar,
useViewMode, useImageRetry и т.д.) — требует рефакторинга: вынести компоненты
в отдельный entry point, настроить `exports` в `package.json`, билд через
`vite build --lib` или `tsup`.

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

**Вариант C — GitHub Packages** (вместо публичного npm):
```bash
# В package.json: "publishConfig": { "registry": "https://npm.pkg.github.com" }
npm publish
```

> ⚠️ Фронтенд сам по себе бесполезен без бэкенда — имеет смысл публиковать
> только как часть документации/шаблона, либо вместе с инструкцией по запуску
> Docker (см. `AGENTS.md`).

---

## 3. Сводная таблица инструментов

| Формат       | Инструмент          | ОС сборки         | Размер    |
|--------------|---------------------|--------------------|-----------|
| `.deb`       | Docker + dpkg-deb  | Linux (Docker)     | ~108 МБ   |
| `.rpm`       | Docker + fpm       | Linux (Docker)     | ~146 МБ   |
| `.AppImage`  | Docker + appimagetool | Linux (Docker)  | ~148 МБ   |
| `.pkg.tar.zst` (Arch/CachyOS) | Docker + makepkg | Linux (Docker) | ~108 МБ |
| `.zip` (Win) | Docker + pip download | Linux (Docker) | ~137 МБ   |
| `.exe` (Win) | Docker + NSIS      | Linux (Docker)     | ~98 МБ    |
| PyInstaller-бандл (macOS) | GitHub Actions + PyInstaller | macOS (CI: arm64) | ~60–90 МБ |
| Docker image | docker compose     | Любая              | ~300 МБ   |

### Рекомендуемый путь

- **Linux (deb/rpm/AppImage, Arch/CachyOS)** — раздел 1 (готовые Docker-скрипты в `packaging/`).
- **Windows (.zip/.exe)** — раздел 1 (Docker-кросс-компиляция из Linux).
- **macOS** — PyInstaller-бандл через CI-воркфлоу `.github/workflows/build-macos.yml`
  (`macos-14` arm64; Intel x64 убран — GitHub сворачивает `macos-13`-раннеры),
  либо Tauri + PyInstaller sidecar (раздел 2, собирается вручную).
- **Серверный/веб-деплой** — Docker (`docker compose up -d --build`, см. `AGENTS.md`).

### CI/CD (GitHub Actions — автосборка Linux-пакетов)

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

### CI/CD — macOS (smoke-test + PyInstaller-бандл)

**Отдельный** воркфлоу `.github/workflows/build-macos.yml` запускается на каждый
push и собирает приложение на `macos-14` (Apple Silicon arm64). Intel x64
(`macos-13`) убран, так как GitHub сворачивает эти раннеры и они больше не
выделяются за разумное время. Он независим от Docker/podman нативной упаковки из
раздела 1 (которая кросс-компилируется из Linux и покрывает deb/rpm/AppImage/arch
+ Windows) — для macOS нет нативного пути упаковки в Docker, поэтому GitHub
Actions-воркфлоу является поддерживаемым маршрутом для Apple Silicon.

Что делает воркфлоу:

1. **Фронтенд** — `npm ci && npm run build` → `frontend/dist/`.
2. **Зависимости бэкенда** — устанавливает `backend/requirements.txt`.
3. **Smoke-тест** — запускает бэкенд (uvicorn) и опрашивает `GET /api/health`
   до получения ответа.
4. **PyInstaller-бандл** (best-effort, `continue-on-error`) — собирает
   `vipergirls-backend` через CLI-флаги. Файла `.spec` пока нет, поэтому флаги
   `--add-data` / `--hidden-import` передаются инлайн.
5. **Артефакты** — загружает `frontend/dist/` и `backend/dist/`.

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
