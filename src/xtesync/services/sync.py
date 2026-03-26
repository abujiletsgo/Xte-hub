"""Sync management service - tracks what needs to sync to device."""

from pathlib import Path

import aiosqlite

from xtesync import database as db


async def mark_generated(conn: aiosqlite.Connection, briefing_date: str, epub_path: str, item_ids: list[int]):
    """Record a generated briefing EPUB."""
    await db.record_briefing(conn, briefing_date, epub_path, item_ids)


async def get_pending(conn: aiosqlite.Connection) -> list[dict]:
    """Get all briefings that haven't been synced to device yet."""
    return await db.get_pending_syncs(conn)


async def mark_synced(conn: aiosqlite.Connection, sync_id: int):
    """Mark a briefing as synced to device."""
    await db.mark_synced(conn, sync_id)


async def get_epub_path(conn: aiosqlite.Connection, briefing_date: str) -> str | None:
    """Get the EPUB file path for a given briefing date."""
    briefing = await db.get_briefing_by_date(conn, briefing_date)
    if briefing and briefing.get("epub_path"):
        path = Path(briefing["epub_path"])
        if path.exists():
            return str(path)
    return None
