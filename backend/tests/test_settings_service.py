"""Runtime settings: schema, coercion, persistence round-trips."""
from app.config import get_settings
from app.services import settings_service
from app.services.settings_service import (
    FORUM_DOMAINS,
    _SCHEMA,
    _coerce,
    get_all_settings,
    get_setting,
    update_settings,
)


def test_schema_shape():
    assert len(_SCHEMA) == 13
    assert _SCHEMA["cache_limit_gb"] == (0.0, float)
    assert _SCHEMA["download_concurrency"] == (8, int)
    assert _SCHEMA["proxy_enabled"] == (True, bool)


def test_coerce_bool():
    for truthy in ("true", "1", "yes", "TRUE", "Yes"):
        assert _coerce(truthy, False, bool) is True
    assert _coerce("false", True, bool) is False
    assert _coerce("0", True, bool) is False
    assert _coerce("no", True, bool) is False


def test_coerce_int():
    assert _coerce("42", 8, int) == 42
    assert _coerce("", 8, int) == 8
    assert _coerce("not-a-number", 8, int) == 8


def test_coerce_float():
    assert _coerce("1.5", 0.0, float) == 1.5
    assert _coerce("0", 0.0, float) == 0.0
    assert _coerce("zzz", 0.0, float) == 0.0


def test_coerce_str_passthrough():
    assert _coerce("hello", "", str) == "hello"
    assert _coerce("", "fallback", str) == "fallback"


async def test_get_setting_defaults():
    assert await get_setting("auto_download") is True
    assert await get_setting("auto_clear_completed") is False
    assert await get_setting("download_concurrency") == 8
    assert await get_setting("cache_limit_gb") == 0.0


async def test_update_settings_roundtrip():
    await update_settings({"download_concurrency": 5, "cache_limit_gb": 2.5})
    assert await get_setting("download_concurrency") == 5
    assert await get_setting("cache_limit_gb") == 2.5


async def test_update_settings_persists_across_cache_reset():
    from app.services import settings_service

    await update_settings({"thread_concurrency": 7})
    # Simulate a process restart: in-memory cache dropped, DB still has it.
    settings_service._cache.clear()
    settings_service._loaded = False
    assert await get_setting("thread_concurrency") == 7


async def test_update_settings_ignores_unknown_keys():
    result = await update_settings({"totally_bogus": 1, "max_retries": 9})
    assert "totally_bogus" not in result
    assert await get_setting("max_retries") == 9


async def test_get_all_settings_defaults():
    result = await get_all_settings()
    assert result["available_domains"] == FORUM_DOMAINS
    # Empty forum_proxy falls back to the config default (viper.to).
    assert result["forum_proxy"] == get_settings().forum_base_url


async def test_get_all_settings_after_proxy_change():
    await update_settings({"forum_proxy": "https://viperbb.rocks"})
    result = await get_all_settings()
    assert result["forum_proxy"] == "https://viperbb.rocks"


def test_forum_domains_are_https_and_include_default():
    assert all(d.startswith("https://") for d in FORUM_DOMAINS)
    assert "https://viper.to" in FORUM_DOMAINS


# ── Env-var seeding (first-boot defaults) ────────────────────────────


def _reload():
    """Simulate a fresh process: new Settings instance + cold settings cache."""
    from app.config import get_settings

    get_settings.cache_clear()
    settings_service._cache.clear()
    settings_service._loaded = False


async def test_env_seeds_absent_keys(monkeypatch):
    monkeypatch.setenv("VIPER_THREAD_CONCURRENCY", "5")
    monkeypatch.setenv("VIPER_CACHE_LIMIT_GB", "1.5")
    _reload()
    assert await get_setting("thread_concurrency") == 5
    assert await get_setting("cache_limit_gb") == 1.5


async def test_env_seed_persists_to_db(monkeypatch):
    from app.db import get_db

    monkeypatch.setenv("VIPER_MAX_RETRIES", "7")
    _reload()
    assert await get_setting("max_retries") == 7
    db = await get_db()
    try:
        row = await (
            await db.execute("SELECT value FROM settings WHERE key='max_retries'")
        ).fetchone()
    finally:
        await db.close()
    assert row is not None and row["value"] == "7"


async def test_env_seed_does_not_override_existing_row(monkeypatch):
    await update_settings({"thread_concurrency": 9})
    monkeypatch.setenv("VIPER_THREAD_CONCURRENCY", "5")
    _reload()
    assert await get_setting("thread_concurrency") == 9


async def test_unset_env_writes_no_row():
    from app.db import get_db

    _reload()
    assert await get_setting("download_concurrency") == 8  # schema default
    db = await get_db()
    try:
        row = await (
            await db.execute(
                "SELECT value FROM settings WHERE key='download_concurrency'"
            )
        ).fetchone()
    finally:
        await db.close()
    assert row is None  # unchanged default must not be frozen into the DB
