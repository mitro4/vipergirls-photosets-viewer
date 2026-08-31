"""Per-host circuit breaker for image hosts.

When an image host goes down (resolver fails, fetch times out or errors
repeatedly), we stop hitting it for a cooldown window so the frontend gets
fast 502s — which surface as the red ✕ fallback — instead of every request
hanging for the full HTTP timeout.  This keeps the page responsive and stops
dead hosts from monopolising the proxy semaphore and the browser's per-host
connection budget.

A page of cards fires dozens of image requests at once; without the breaker
each one independently pays the full resolver+fetch timeout against a host
that is never going to answer, freezing the tab for tens of seconds.  After
``_FAILURE_THRESHOLD`` failures the host is short-circuited for
``_COOLDOWN_SECONDS``; the next request after the cooldown is allowed through
as a probe (half-open) — if it fails, the host re-trips immediately, if it
succeeds the failure count is cleared.

State is process-local and in-memory; it resets on restart, which is fine —
we only need to ride out transient outages, not survive them across reboots.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

log = logging.getLogger("viper.hosts")

# Trip the breaker after this many consecutive failures from a host.
_FAILURE_THRESHOLD = 3
# While open, fail fast for this long before letting a probe request through.
_COOLDOWN_SECONDS = 60.0


@dataclass
class _HostState:
    failures: int = 0
    dead_until: float = 0.0  # monotonic timestamp; 0.0 == healthy


_state: dict[str, _HostState] = {}


def is_host_dead(host: str) -> bool:
    """True if *host* is within its fail-fast cooldown window."""
    if not host:
        return False
    s = _state.get(host)
    return bool(s) and time.monotonic() < s.dead_until


def record_host_failure(host: str) -> None:
    """Record a failed fetch from *host*; trip the breaker if persistent."""
    if not host:
        return
    s = _state.setdefault(host, _HostState())
    s.failures += 1
    now = time.monotonic()
    # Only (re)open the breaker when not already open, so a probe failure
    # right after cooldown re-trips it in one shot.
    if s.failures >= _FAILURE_THRESHOLD and s.dead_until <= now:
        s.dead_until = now + _COOLDOWN_SECONDS
        log.warning(
            "Image host %s marked unavailable for %.0fs after %d consecutive failures",
            host,
            _COOLDOWN_SECONDS,
            s.failures,
        )


def record_host_success(host: str) -> None:
    """Clear the failure count for *host* once it serves an image again."""
    if not host:
        return
    s = _state.get(host)
    if s and (s.failures or s.dead_until):
        s.failures = 0
        s.dead_until = 0.0
