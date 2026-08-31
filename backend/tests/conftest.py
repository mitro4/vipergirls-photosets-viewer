"""Shared test fixtures.

``DATA_DIR`` is read at *module import time* by ``app.config`` (not via
pydantic), so it must be pointed at a temp dir BEFORE any ``app.*`` import —
pytest imports this conftest first, which is why the env var is set at the
top of the module, not inside a fixture.
"""
from __future__ import annotations

import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="viper-tests-")
os.environ["DATA_DIR"] = _TMP

import asyncio  # noqa: E402

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import close_pool, get_db, init_db  # noqa: E402
from app.services import settings_service  # noqa: E402


@pytest.fixture(autouse=True)
async def fresh_db():
    """Fresh schema + pristine settings cache for every test.

    The module-level ``asyncio.Lock`` in settings_service binds to the first
    event loop that acquires it; pytest-asyncio gives each test a new loop,
    so the lock must be recreated alongside the cache.
    """
    await init_db()
    # init_db only does CREATE TABLE IF NOT EXISTS — rows persist in the
    # session-wide temp DB, so wipe the settings table for true isolation.
    db = await get_db()
    try:
        await db.execute("DELETE FROM settings")
        await db.commit()
    finally:
        await db.close()
    settings_service._cache.clear()
    settings_service._loaded = False
    settings_service._lock = asyncio.Lock()
    yield
    await close_pool()
    # Drop the lru-cached Settings so a test that monkeypatched VIPER_* env
    # vars doesn't leak them into the next test's instance.
    get_settings.cache_clear()
