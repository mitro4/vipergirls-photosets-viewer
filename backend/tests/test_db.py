"""SQLite init + connection-pool recycling (db.py)."""
from app.db import _POOL_SIZE, get_db, init_db

_EXPECTED_TABLES = {
    "categories", "threads", "images", "forum_pages", "settings",
    "liked_threads", "downloads", "download_queue",
}


async def test_init_creates_all_tables():
    db = await get_db()
    try:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        names = {row["name"] for row in await cur.fetchall()}
        await cur.close()
    finally:
        await db.close()
    assert _EXPECTED_TABLES <= names


async def test_pool_recycles_connections():
    db1 = await get_db()
    conn1 = db1._conn
    await db1.close()
    db2 = await get_db()
    conn2 = db2._conn
    await db2.close()
    assert conn1 is conn2


async def test_double_close_is_idempotent():
    db = await get_db()
    await db.close()
    await db.close()  # must not release the pool slot twice
    # All POOL_SIZE slots must still be acquirable afterwards.
    conns = [await get_db() for _ in range(_POOL_SIZE)]
    for c in conns:
        await c.close()


async def test_concurrent_acquires_within_pool_size():
    dbs = [await get_db() for _ in range(_POOL_SIZE)]
    for db in dbs:
        cur = await db.execute("SELECT 1 AS one")
        row = await cur.fetchone()
        assert row["one"] == 1
    for db in dbs:
        await db.close()
