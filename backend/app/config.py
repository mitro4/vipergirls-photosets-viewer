"""Application configuration loaded from environment variables."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIPER_", env_file=".env", extra="ignore")

    username: str = ""
    password_md5: str = ""

    request_limit: int = 2
    # Rate for the multi-batch sidebar-scoped search fan-out (higher than the
    # general request_limit because an unscoped search issues several sequential
    # do=process/showresults calls that would otherwise be painfully slow).
    search_request_limit: float = 4.0

    forum_base_url: str = "https://viper.to"
    click_base_url: str = "https://viper.click"
    login_base_url: str = "https://vipergirls.to"

    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:136.0) Gecko/20100101 Firefox/136.0"
    )

    db_path: Path = DATA_DIR / "viper.db"
    cache_dir: Path = DATA_DIR / "cache"

    # ── Env-only knobs (read directly, no runtime override) ──────────
    per_host_concurrency: int = 2

    # ── Seeds for the runtime settings table (settings_service) ──────
    # Applied ONCE, when the key is absent from the DB (first boot);
    # afterwards the UI value (settings table) wins and the env var is
    # ignored. See settings_service._ensure_loaded().
    download_concurrency: int = 8
    thread_concurrency: int = 2
    download_timeout: int = 30
    max_retries: int = 3
    cache_limit_gb: float = 0.0

    @property
    def data_dir(self) -> Path:
        return DATA_DIR


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.cache_dir.mkdir(parents=True, exist_ok=True)
    return s
