"""SQLite database initialization and connection pooling (aiosqlite).

``get_db()`` hands out pooled connections. Callers keep the existing
``db = await get_db(); try: ...; finally: await db.close()`` idiom — ``close()``
returns the connection to the pool instead of tearing it down. Opening an
aiosqlite connection spawns a worker thread and runs PRAGMAs; doing that on
every call (2+ per /api/image request) was a measurable hot-path cost.

WAL is a persistent property of the database file, set once in ``init_db``.
Each pooled connection gets ``busy_timeout`` (concurrent writers under WAL
wait instead of failing with SQLITE_BUSY) and ``synchronous=NORMAL`` (WAL +
NORMAL skips the per-commit fsync; durability loss on power failure is
acceptable for a cache DB).
"""
from __future__ import annotations

import asyncio

import aiosqlite

from .config import get_settings

_POOL_SIZE = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    slug TEXT NOT NULL DEFAULT '',
    forum_id INTEGER NOT NULL,
    parent_id INTEGER,
    thread_count INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    forum_id INTEGER NOT NULL,
    prefix TEXT DEFAULT '',
    author TEXT DEFAULT '',
    posted_at TEXT DEFAULT '',
    replies INTEGER DEFAULT 0,
    views INTEGER DEFAULT 0,
    cover_url TEXT DEFAULT '',
    preview_urls_json TEXT DEFAULT '[]',
    image_count INTEGER DEFAULT 0,
    meta_fetched INTEGER DEFAULT 0,
    fetched_at TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_threads_forum ON threads(forum_id);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    post_id INTEGER DEFAULT 0,
    main_url TEXT NOT NULL,
    thumb_url TEXT DEFAULT '',
    host TEXT DEFAULT '',
    resolved_url TEXT DEFAULT '',
    status TEXT DEFAULT 'pending',
    fetched_at TEXT DEFAULT '',
    UNIQUE(thread_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_images_thread ON images(thread_id);

CREATE TABLE IF NOT EXISTS forum_pages (
    forum_id INTEGER NOT NULL,
    page INTEGER NOT NULL,
    threads_json TEXT NOT NULL,
    total_pages INTEGER DEFAULT 1,
    total_threads INTEGER DEFAULT 0,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (forum_id, page)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS liked_threads (
    thread_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    post_id INTEGER DEFAULT 0,
    liked_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS downloads (
    thread_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL DEFAULT '',
    downloaded_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS download_queue (
    thread_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL DEFAULT ''
);
"""


class _Pool:
    """Bounded pool of aiosqlite connections.

    ``acquire`` blocks (on a semaphore) when all connections are checked out,
    so callers that hold a connection across a long await can stall others —
    never nest ``get_db()`` calls while another connection is held.
    """

    def __init__(self, size: int) -> None:
        self._size = size
        self._sem = asyncio.Semaphore(size)
        self._idle: list[aiosqlite.Connection] = []
        self._all: list[aiosqlite.Connection] = []

    async def acquire(self) -> aiosqlite.Connection:
        await self._sem.acquire()
        if self._idle:
            return self._idle.pop()
        conn = await aiosqlite.connect(str(get_settings().db_path))
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA busy_timeout=5000;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        # 256 MB memory-mapped I/O + 64 MB page cache: the images table is by
        # far the hottest read path (every /api/image lookup).
        await conn.execute("PRAGMA mmap_size=268435456;")
        await conn.execute("PRAGMA cache_size=-65536;")
        self._all.append(conn)
        return conn

    async def release(self, conn: aiosqlite.Connection) -> None:
        # Never hand out a connection stuck in an uncommitted transaction —
        # it would leak read/write locks to the next borrower.
        try:
            if conn.in_transaction:
                await conn.rollback()
        except Exception:
            pass
        self._idle.append(conn)
        self._sem.release()

    async def close_all(self) -> None:
        for conn in self._all:
            try:
                await conn.close()
            except Exception:
                pass
        self._all.clear()
        self._idle.clear()


_pool: _Pool | None = None


def _get_pool() -> _Pool:
    global _pool
    if _pool is None:
        _pool = _Pool(_POOL_SIZE)
    return _pool


class _PooledDb:
    """Duck-typed aiosqlite.Connection facade whose ``close()`` recycles the
    connection into the pool. Idempotent — a double ``close()`` (as in
    ``get_thread_posts``) only releases once."""

    def __init__(self, conn: aiosqlite.Connection, pool: _Pool) -> None:
        self._conn = conn
        self._pool = pool
        self._released = False

    async def execute(self, sql: str, parameters=()):
        return await self._conn.execute(sql, parameters)

    async def executemany(self, sql: str, seq_of_parameters):
        return await self._conn.executemany(sql, seq_of_parameters)

    async def executescript(self, script: str):
        return await self._conn.executescript(script)

    async def commit(self) -> None:
        await self._conn.commit()

    async def rollback(self) -> None:
        await self._conn.rollback()

    async def close(self) -> None:
        if self._released:
            return
        self._released = True
        await self._pool.release(self._conn)


async def get_db() -> _PooledDb:
    """Acquire a pooled DB connection. Always ``await db.close()`` when done —
    that returns it to the pool (no thread is torn down)."""
    pool = _get_pool()
    conn = await pool.acquire()
    return _PooledDb(conn, pool)


async def close_pool() -> None:
    """Close every pooled connection (called on app shutdown)."""
    global _pool
    if _pool is not None:
        await _pool.close_all()
        _pool = None


async def init_db() -> None:
    db = await get_db()
    try:
        # WAL is persistent in the DB file — setting it once at startup is
        # enough (re-setting it per connection takes a write lock).
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.executescript(_SCHEMA)
        # One-time fix: threads parsed before directlinked-image support (GIF
        # collections etc.) were cached with image_count=0 and filtered out of
        # listings. Reset them so they re-parse with the fixed parser.
        done = await (
            await db.execute(
                "SELECT value FROM settings WHERE key=?", ("fix_directlinked",)
            )
        ).fetchone()
        if not done:
            await db.execute(
                "UPDATE threads SET meta_fetched=0 "
                "WHERE meta_fetched=1 AND image_count=0"
            )
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                ("fix_directlinked", "1"),
            )
        await db.commit()
    finally:
        await db.close()
