# ViperGirls Photo Sets Viewer

Browse photo sets from the viper.to forum with a clean, fast desktop or web UI:
large covers, hover-to-preview carousel, full-screen lightbox with slideshow,
a persistent download queue (per-thread folders on desktop, streamed ZIP on
web), likes & downloads history, numbered pagination, live forum search, and
SOCKS5/HTTP proxy support for ISP-blocked access.

Runs in three ways:

| Mode | Best for | Requirements |
|---|---|---|
| **Desktop app** (Windows `.exe`, Linux `.deb`/`.rpm`/`.AppImage`) | End users — no tech skills needed | Just download & run |
| **Docker** | Self-hosting on a server/NAS | Docker |
| **Dev mode** | Contributors | Python 3.12 + Node.js 20 |

---

## Features

- **Desktop GUI** — native window (Electron/Chromium) with embedded Python
  backend. No browser, no Docker, no terminal — just double-click the app.
- **Category navigation** — all Photo Sets sections (Softcore, Hardcore, Fetish,
  Lesbian, Transsexual, Gay, etc.) in a sidebar, with a **Back** button in the
  header to return from a thread. Keep-alive navigation returns to the gallery
  instantly (no reload, scroll position preserved).
- **Wave-based progressive loading** — cards load in coordinated waves: first
  all cover thumbnails across every card, then previews, then each card
  upgrades to medium quality one image at a time. Smooth swap (brightness flash)
  — no blank flashes or broken icons.
- **Hover-to-preview** — mouse across a cover scrubs through the first 5 photos
  of the set (5-zone crossfade carousel with progress bar).
- **Full photo-set viewer** — thumbnail grid (paginated 12 images per page,
  grouped by post) + full-screen lightbox with keyboard navigation, zoom,
  swipe, per-image download, ±1 neighbour preloading, and a Play/Pause
  slideshow toggle with an adjustable 1–5 second interval.
- **Download queue** — a persistent queue (survives app restart) replaces the
  old download popup. A toolbar button with an active-count badge opens the
  queue panel: each row shows the thread title, status, and `[downloaded/total]`
  progress, with STOP/START controls per row and a Clear-queue button. Threads
  download up to `thread_concurrency` in parallel, in queue order. A download
  button on each card's top-right corner adds a thread to the queue. On the
  desktop app each photoset saves into its own folder (named after the thread,
  hardlinked from the cache so disk isn't double-spent); in Docker/web mode a
  ZIP is streamed instead. Host interstitials are resolved on-the-fly and
  cached. Failed images can be retried.
- **Likes** — tap the heart on any card to like the thread on the forum (via
  the vBulletin "thanks" mechanism). A dedicated **Liked** view lists every
  thread you've liked, with the same grid, selection, and batch download.
- **Downloads history** — the **Downloads** view lists every thread you've
  saved with an "Open folder" action (desktop) that reveals it in your file
  manager. Records of deleted folders are pruned automatically.
- **Persistent login** — your forum session is saved across restarts, so you
  stay logged in.
- **Numbered pagination** — first / previous / page-window / next / last
  controls on every listing (categories, search, thread), duplicated top &
  bottom.
- **Network proxy** — SOCKS5/SOCKS5h/HTTP proxy support (with optional
  authentication) for when your ISP blocks the forum or image hosts. Toggle
  on/off without losing saved credentials. Applies to both forum scraping and
  image fetching.
- **Forum login** — optional vBulletin authentication for member-only threads.
- **Search** — live forum search (vBulletin Advanced Search) scoped to any
  combination of sections, with pagination, cached cover enrichment, and
  results sorted by post date.
- **16 image hosts** — imx.to, imgbox, pixhost, imagevenue, imagetwist, acidimg,
  imagebam, pimpandhost, postimg, turboimagehost, vipr.im, and more.
  Interstitial pages are resolved on-the-fly and cached. The `pixhost` matcher
  covers both the `.to` and `.cc` mirrors (pure URL transform, no DNS). When a
  full image fails (e.g. turboimagehost or imx.to behind a challenge), the
  cached thumbnail is served as a degraded fallback. GIF animation is preserved.
- **Disk caching** — resolved images are cached with no size cap. Settings
  shows the current cache size and a Clear-cache button. Per-host concurrency
  caps keep one slow host from stalling the rest. Circuit breaker marks dead
  hosts for instant 502 instead of timing out.
- **Configurable concurrency** — `download_concurrency` (shared budget for
  interactive viewing + ZIP downloads + background prefetch) and
  `thread_concurrency` (batch covers, parallel queue workers, multi-thread
  ZIP). Adjustable at runtime.

---

## Quick start

### Desktop app (recommended for most users)

Download the latest release for your OS:

- **Windows**: `vipergirls-viewer-*-win-x64-setup.exe` (installer) or
  `*-portable.zip` (no install, just unzip and run)
- **Linux**: `.deb` (Debian/Ubuntu), `.rpm` (Fedora/openSUSE), or
  `.AppImage` (any distro, per-user, no install)

Launch the app — it opens a native window, starts the embedded backend, and
you're browsing. Data is stored per-user (`%APPDATA%` on Windows,
`~/.local/share` on Linux).

### Docker

```bash
cp .env.example .env        # optional: add forum credentials for member-only sets
docker compose up -d --build
```

Open **http://localhost:8888**.

### Development

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# Frontend (proxies /api → :8000)
cd frontend && npm install && npm run dev
```

---

## Building packages from source

All packages are built reproducibly in Docker — **no local toolchain needed**
(just Docker on a Linux host). Build scripts live in `packaging/scripts/`.

### Linux (deb / rpm / AppImage)

```bash
./packaging/scripts/build-deb.sh        # → dist-packages/*.deb
./packaging/scripts/build-rpm.sh        # → dist-packages/*.rpm
./packaging/scripts/build-appimage.sh   # → dist-packages/*.AppImage

# All three at once:
./packaging/scripts/build-all.sh
```

Each package bundles a self-contained Python 3.12 runtime + Electron
(Chromium). The deb/rpm install a `.desktop` entry, systemd service (server
mode on `:8000`), and per-user data storage. AppImage is a single portable
file.

### Windows (portable ZIP + NSIS installer)

Cross-compiled from Linux — **no Wine or Windows host required**:

```bash
./packaging/scripts/build-windows.sh    # → dist-packages/*-win-x64-*
```

Produces:
- `*-win-x64-portable.zip` (~137 MB) — unzip and run `electron\electron.exe`
- `*-win-x64-setup.exe` (~98 MB) — NSIS installer with Start Menu + Desktop
  shortcuts and uninstaller

Uses the Windows embeddable Python 3.12 (all deps have prebuilt win_amd64
wheels) and Electron for Windows.

### Docker image

```bash
docker compose up -d --build   # builds + runs the full stack
```

See `PACKAGING.md` for detailed build architecture and `AGENTS.md` for
developer documentation.

---

## Configuration

### Environment variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `VIPER_USERNAME` | _(empty)_ | Forum username (optional) |
| `VIPER_PASSWORD_MD5` | _(empty)_ | MD5 of your forum password (optional) |
| `VIPER_REQUEST_LIMIT` | `2` | Max requests/sec to the forum |
| `VIPER_DOWNLOAD_CONCURRENCY` | `8` | First-boot seed for the `download_concurrency` runtime setting |
| `VIPER_THREAD_CONCURRENCY` | `2` | First-boot seed for `thread_concurrency` |
| `VIPER_DOWNLOAD_TIMEOUT` | `30` | First-boot seed for `download_timeout` (sec) |
| `VIPER_MAX_RETRIES` | `3` | First-boot seed for `max_retries` |
| `VIPER_CACHE_LIMIT_GB` | `0` | First-boot seed for the cache LRU-trim ceiling, GB (0 = unlimited) |

Seed variables are applied **once** — when the key is absent from the settings
DB (first boot). After that the value set in the app UI wins and the env var is
ignored. Docker Compose passes the whole `.env` file into the container
automatically.

### Runtime settings (in-app)

Editable in the Settings dialog, persisted in SQLite (`GET/PUT /api/settings`):

- **Proxy** — `socks5://`, `socks5h://`, `http://` with optional
  `proxy_username`/`proxy_password`. Toggle on/off via `proxy_enabled` without
  losing saved credentials. Applies to both forum scraper and image hosts.
- **Concurrency** — `download_concurrency` (shared: viewing + ZIP + prefetch),
  `thread_concurrency` (batch covers + multi-thread ZIP).
- **Forum mirror** — switch between known forum mirrors (planetviper.club,
  viperbb.rocks, viperkats.eu, etc.) at runtime.
- **Download** — `order_images` (sequential filenames), `download_timeout`,
  `max_retries`, plus two toggles: **auto-download when added to queue**
  (default on) and **auto-clear when a thread finishes** (default off).
- **Cache** — optional size cap (`cache_limit_gb`, 0 = unlimited): when set,
  a background job LRU-trims the on-disk image cache every 30 minutes. Settings
  shows the current cache size and a Clear-cache button (`POST /api/cache/clear`).
- **Downloads folder** — where per-thread image folders are saved (desktop
  only; chosen via the OS folder dialog and persisted across restarts).

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/categories` | List all Photo Sets categories grouped by section |
| GET | `/api/forums/{id}/threads?page=N` | Thread listing for a forum page |
| GET | `/api/thread/{id}` | Full photo-set data (all images) |
| GET | `/api/thread/{id}/cover` | Cover + first 5 preview thumbnails |
| POST | `/api/threads/covers` | Batch-resolve covers for many thread ids |
| GET | `/api/thread/{id}/posts?page=N` | One page of posts (grouped images) |
| GET | `/api/thread/{id}/download` | Stream ZIP of all images |
| GET | `/api/image/{id}?size=thumb\|medium\|full` | Proxied image (resolves host, caches) |
| GET | `/api/proxy?url=...` | Proxy an arbitrary image URL |
| GET | `/api/search?q=...&forums=...` | Live forum search (scoped, paginated) |
| GET | `/api/stats` | Cache/thread/image statistics |
| POST | `/api/cache/clear` | Clear image disk cache |
| POST | `/api/download/multi` | Start a multi-thread background download job |
| GET | `/api/download/{job_id}/status` | Poll a download job's progress |
| POST | `/api/download/{job_id}/retry` | Re-attempt a job's failed images |
| GET | `/api/download/{job_id}/zip` | Stream the ZIP of a completed job |
| POST | `/api/thread/{id}/like` | Like a thread on the forum (vBulletin "thanks") |
| DELETE | `/api/thread/{id}/like` | Remove a like |
| GET | `/api/liked` | List threads you've liked |
| GET | `/api/downloads` | List downloaded threads + current folder |
| POST | `/api/downloads/folder` | Set the downloads folder (reported by Electron) |
| GET | `/api/auth/status` | Check login status |
| POST | `/api/auth/login` | Log in (JSON: username, password) |
| POST | `/api/auth/logout` | Log out |
| GET | `/api/settings` | Get runtime settings |
| PUT | `/api/settings` | Update runtime settings |

---

## Architecture

- **Backend** — Python / FastAPI. Scrapes via `viper.click/vr.php` (clean XML)
  with a direct `viper.to` fallback using `curl_cffi` (Cloudflare bypass).
  Resolves 16 inline image hosts and streams ZIPs on demand. Rate-limited to the
  forum (token bucket, 2 req/s default). SQLite for caching (threads, images,
  resolved URLs, settings).
- **Frontend** — React + TypeScript + Vite + TailwindCSS. TanStack Query for
  data fetching, wave-based progressive image loading, keep-alive category
  navigation, 5-zone hover carousel, lightbox with keyboard/touch nav + ±1
  preload, react-window virtualisation for large grids.
- **Desktop** — Electron main process spawns the Python backend as a child
  process, waits for `/api/health`, opens a Chromium BrowserWindow. A preload
  bridge exposes open-folder / choose-folder IPC, and downloads auto-save to a
  configurable folder. Backend is reused if already running (e.g. systemd).
  F12 opens DevTools.
- **Container** — Multi-stage Docker build: Node builds the SPA, then a Python
  image runs uvicorn (API) behind Caddy (static files + reverse proxy).

---

## License

This project is for personal use. Respect the forum's terms of service and
content creators' rights.
