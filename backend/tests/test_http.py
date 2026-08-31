"""Leaky-bucket rate limiter + per-host limiter lookup (scrapers/http.py)."""
import time

from app.scrapers.http import HttpClient, RateLimiter


async def test_zero_rate_never_waits():
    lim = RateLimiter(0)
    start = time.monotonic()
    for _ in range(10):
        await lim.acquire()
    assert time.monotonic() - start < 0.05


async def test_rate_enforces_min_spacing():
    lim = RateLimiter(50)  # 20 ms between acquires
    await lim.acquire()
    start = time.monotonic()
    await lim.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.015  # ~20ms minus scheduling slop


def test_rate_for_is_per_host():
    client = HttpClient()
    l_to1 = client._rate_for("https://viper.to/forumdisplay.php?f=1")
    l_to2 = client._rate_for("https://viper.to/showthread.php?t=2")
    l_click = client._rate_for("https://viper.click/vr.php?id=3")
    assert l_to1 is l_to2
    assert l_to1 is not l_click


def test_rate_for_unknown_host_uses_empty_string_key():
    client = HttpClient()
    lim = client._rate_for("/relative/url")
    assert client._rate_for("/another") is lim
