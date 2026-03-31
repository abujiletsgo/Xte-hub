"""Database schema, connection management, and query functions for XteSync."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

DB_PATH = Path(__file__).parent.parent.parent / "data" / "xtesync.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL UNIQUE,
    title           TEXT,
    source_domain   TEXT,
    content_type    TEXT DEFAULT 'article',
    category        TEXT,
    auto_category   TEXT,
    auto_category_confidence REAL,
    content_text    TEXT,
    content_html    TEXT,
    summary         TEXT,
    detail          TEXT,
    summary_epub_path TEXT,
    full_epub_path  TEXT,
    word_count      INTEGER,
    cluster_id      INTEGER REFERENCES story_clusters(id),
    submitted_at    TEXT NOT NULL DEFAULT (datetime('now')),
    processed_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    error_message   TEXT
);

CREATE TABLE IF NOT EXISTS story_clusters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    slug            TEXT NOT NULL UNIQUE,
    headline        TEXT NOT NULL,
    category        TEXT NOT NULL,
    synthesis       TEXT,
    key_facts       TEXT,
    source_agreement TEXT,
    item_count      INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS cluster_items (
    cluster_id  INTEGER NOT NULL REFERENCES story_clusters(id),
    item_id     INTEGER NOT NULL REFERENCES items(id),
    role        TEXT DEFAULT 'member',
    added_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (cluster_id, item_id)
);

CREATE TABLE IF NOT EXISTS sync_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_date   TEXT NOT NULL UNIQUE,
    epub_path       TEXT,
    generated_at    TEXT,
    synced_at       TEXT,
    item_ids_json   TEXT
);

CREATE TABLE IF NOT EXISTS channels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT NOT NULL UNIQUE,
    name            TEXT,
    platform        TEXT NOT NULL DEFAULT 'youtube',
    category        TEXT DEFAULT 'general',
    added_at        TEXT NOT NULL DEFAULT (datetime('now')),
    last_fetched    TEXT,
    enabled         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_items_category ON items(category);
CREATE INDEX IF NOT EXISTS idx_items_cluster ON items(cluster_id);
CREATE INDEX IF NOT EXISTS idx_items_submitted ON items(submitted_at);
CREATE INDEX IF NOT EXISTS idx_clusters_category ON story_clusters(category);
CREATE INDEX IF NOT EXISTS idx_channels_enabled ON channels(enabled);
"""


async def get_db() -> aiosqlite.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(DB_PATH))
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


@asynccontextmanager
async def get_db_ctx():
    db = await get_db()
    try:
        yield db
    finally:
        await db.close()


async def init_db():
    async with get_db_ctx() as db:
        await db.executescript(SCHEMA)
        await db.commit()


# --- Item queries ---

async def insert_item(db: aiosqlite.Connection, url: str, content_type: str = "article", category: str | None = None) -> int:
    cursor = await db.execute(
        """INSERT INTO items (url, content_type, category, status)
           VALUES (?, ?, ?, 'pending')
           ON CONFLICT(url) DO UPDATE SET status='pending', error_message=NULL, processed_at=NULL
           RETURNING id""",
        (url, content_type, category),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row[0]


async def update_item_extracted(db: aiosqlite.Connection, item_id: int, **kwargs):
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [item_id]
    await db.execute(f"UPDATE items SET {sets} WHERE id = ?", vals)
    await db.commit()


async def update_item_status(db: aiosqlite.Connection, item_id: int, status: str, error_message: str | None = None):
    await db.execute(
        "UPDATE items SET status = ?, error_message = ?, processed_at = datetime('now') WHERE id = ?",
        (status, error_message, item_id),
    )
    await db.commit()


async def get_item(db: aiosqlite.Connection, item_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_items(db: aiosqlite.Connection, status: str | None = None, category: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    conditions = []
    params: list = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if category:
        conditions.append("(category = ? OR auto_category = ?)")
        params.extend([category, category])
    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    cursor = await db.execute(
        f"SELECT * FROM items {where} ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return [dict(r) for r in await cursor.fetchall()]


async def get_unprocessed_items_for_briefing(db: aiosqlite.Connection, since_hours: int = 48) -> list[dict]:
    cursor = await db.execute(
        """SELECT * FROM items
           WHERE status = 'ready'
             AND submitted_at >= datetime('now', ?)
           ORDER BY submitted_at DESC""",
        (f"-{since_hours} hours",),
    )
    return [dict(r) for r in await cursor.fetchall()]


# --- Cluster queries ---

async def create_cluster(db: aiosqlite.Connection, slug: str, headline: str, category: str,
                         synthesis: str | None = None, key_facts: list | None = None,
                         source_agreement: str | None = None) -> int:
    cursor = await db.execute(
        """INSERT INTO story_clusters (slug, headline, category, synthesis, key_facts, source_agreement)
           VALUES (?, ?, ?, ?, ?, ?)
           RETURNING id""",
        (slug, headline, category, synthesis,
         json.dumps(key_facts) if key_facts else None,
         source_agreement),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row[0]


async def add_item_to_cluster(db: aiosqlite.Connection, cluster_id: int, item_id: int, role: str = "member"):
    await db.execute(
        "INSERT OR IGNORE INTO cluster_items (cluster_id, item_id, role) VALUES (?, ?, ?)",
        (cluster_id, item_id, role),
    )
    await db.execute(
        "UPDATE items SET cluster_id = ? WHERE id = ?", (cluster_id, item_id)
    )
    await db.execute(
        "UPDATE story_clusters SET item_count = (SELECT COUNT(*) FROM cluster_items WHERE cluster_id = ?), updated_at = datetime('now') WHERE id = ?",
        (cluster_id, cluster_id),
    )
    await db.commit()


async def update_cluster_synthesis(db: aiosqlite.Connection, cluster_id: int, synthesis: str,
                                    key_facts: list | None = None, source_agreement: str | None = None):
    await db.execute(
        """UPDATE story_clusters
           SET synthesis = ?, key_facts = ?, source_agreement = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (synthesis, json.dumps(key_facts) if key_facts else None, source_agreement, cluster_id),
    )
    await db.commit()


async def get_cluster_with_items(db: aiosqlite.Connection, cluster_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM story_clusters WHERE id = ?", (cluster_id,))
    cluster = await cursor.fetchone()
    if not cluster:
        return None
    cluster = dict(cluster)
    cursor = await db.execute(
        """SELECT i.* FROM items i
           JOIN cluster_items ci ON ci.item_id = i.id
           WHERE ci.cluster_id = ?""",
        (cluster_id,),
    )
    cluster["items"] = [dict(r) for r in await cursor.fetchall()]
    if cluster.get("key_facts"):
        cluster["key_facts"] = json.loads(cluster["key_facts"])
    return cluster


async def get_clusters_by_category(db: aiosqlite.Connection, category: str) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM story_clusters WHERE category = ? ORDER BY created_at DESC",
        (category,),
    )
    clusters = [dict(r) for r in await cursor.fetchall()]
    for c in clusters:
        if c.get("key_facts"):
            c["key_facts"] = json.loads(c["key_facts"])
    return clusters


# --- Sync queries ---

async def record_briefing(db: aiosqlite.Connection, briefing_date: str, epub_path: str, item_ids: list[int]):
    await db.execute(
        """INSERT INTO sync_state (briefing_date, epub_path, generated_at, item_ids_json)
           VALUES (?, ?, datetime('now'), ?)
           ON CONFLICT(briefing_date) DO UPDATE SET
             epub_path = excluded.epub_path,
             generated_at = excluded.generated_at,
             item_ids_json = excluded.item_ids_json,
             synced_at = NULL""",
        (briefing_date, epub_path, json.dumps(item_ids)),
    )
    await db.commit()


async def get_pending_syncs(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM sync_state WHERE synced_at IS NULL ORDER BY briefing_date DESC"
    )
    return [dict(r) for r in await cursor.fetchall()]


async def mark_synced(db: aiosqlite.Connection, sync_id: int):
    await db.execute(
        "UPDATE sync_state SET synced_at = datetime('now') WHERE id = ?",
        (sync_id,),
    )
    await db.commit()


async def get_briefing_by_date(db: aiosqlite.Connection, briefing_date: str) -> dict | None:
    cursor = await db.execute(
        "SELECT * FROM sync_state WHERE briefing_date = ?", (briefing_date,)
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


# --- Channel queries ---

async def add_channel(db: aiosqlite.Connection, handle: str, name: str | None = None,
                      category: str = "general") -> int:
    cursor = await db.execute(
        """INSERT INTO channels (handle, name, category)
           VALUES (?, ?, ?)
           ON CONFLICT(handle) DO UPDATE SET name=COALESCE(excluded.name, channels.name),
             category=excluded.category, enabled=1
           RETURNING id""",
        (handle, name, category),
    )
    row = await cursor.fetchone()
    await db.commit()
    return row[0]


async def get_channels(db: aiosqlite.Connection, enabled_only: bool = True) -> list[dict]:
    where = "WHERE enabled = 1" if enabled_only else ""
    cursor = await db.execute(f"SELECT * FROM channels {where} ORDER BY category, name")
    return [dict(r) for r in await cursor.fetchall()]


async def remove_channel(db: aiosqlite.Connection, channel_id: int):
    await db.execute("UPDATE channels SET enabled = 0 WHERE id = ?", (channel_id,))
    await db.commit()


async def update_channel_fetched(db: aiosqlite.Connection, channel_id: int):
    await db.execute(
        "UPDATE channels SET last_fetched = datetime('now') WHERE id = ?",
        (channel_id,),
    )
    await db.commit()
