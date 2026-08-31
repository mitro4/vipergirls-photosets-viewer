#!/bin/bash
set -e

echo "[entrypoint] Starting uvicorn (FastAPI)…"
uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info &
UVICORN_PID=$!

# Wait briefly for uvicorn to be ready
for i in $(seq 1 15); do
    if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        echo "[entrypoint] uvicorn is ready."
        break
    fi
    sleep 1
done

echo "[entrypoint] Starting Caddy…"
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
CADDY_PID=$!

# Forward signals and wait
trap "kill $UVICORN_PID $CADDY_PID 2>/dev/null; exit" INT TERM

wait -n "$UVICORN_PID" "$CADDY_PID"
echo "[entrypoint] A process exited, shutting down."
kill "$UVICORN_PID" "$CADDY_PID" 2>/dev/null || true
