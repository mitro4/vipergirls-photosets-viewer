"""Server launcher for vipergirls-viewer.

Runs uvicorn (FastAPI backend) in the foreground.  This module is used in two
contexts:

1. **Native packages (deb/rpm/AppImage)** — the Electron main process spawns
   ``python -m app.launcher --no-gui`` as a child process and renders the SPA
   in a Chromium BrowserWindow.

2. **Server mode (systemd)** — the systemd unit calls ``run.sh --no-gui`` which
   runs this module directly.

The ``--no-gui`` flag is accepted for backward compatibility but is now the
default behaviour — there is no GUI mode in this module.  GUI rendering is
handled entirely by Electron.

Usage::

    python -m app.launcher            # run uvicorn in foreground
    python -m app.launcher --no-gui   # same thing (explicit)
"""
from __future__ import annotations

import argparse
import logging
import os

import uvicorn

log = logging.getLogger("launcher")

HOST = os.environ.get("VIPER_HOST", "127.0.0.1")
PORT = int(os.environ.get("VIPER_PORT", "8000"))


def main() -> None:
    parser = argparse.ArgumentParser(description="ViperGirls Viewer server launcher")
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="(deprecated — always server-only) kept for backward compatibility",
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log.info("starting uvicorn on %s:%s", args.host, args.port)
    config = uvicorn.Config(
        "app.main:app",
        host=args.host,
        port=args.port,
        log_level=os.environ.get("VIPER_LOG_LEVEL", "info"),
    )
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()
