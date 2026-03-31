"""Feed service — fetches recent videos from subscribed YouTube channels."""

import json
import logging
import subprocess
from datetime import datetime, timedelta

from xtesync import database as db
from xtesync.services import content

logger = logging.getLogger(__name__)

# How many recent videos per channel (keep lean — quality over quantity)
VIDEOS_PER_CHANNEL = 2
# Only ingest videos from the last N days
RECENCY_DAYS = 7


async def fetch_all_channels(since_days: int = RECENCY_DAYS) -> dict:
    """Fetch recent videos from all enabled channels.

    Returns summary: {fetched: int, new: int, skipped: int, errors: []}
    """
    async with db.get_db_ctx() as conn:
        channels = await db.get_channels(conn, enabled_only=True)

    result = {"fetched": 0, "new": 0, "skipped": 0, "errors": []}

    for ch in channels:
        try:
            stats = await fetch_channel(ch, since_days=since_days)
            result["fetched"] += stats["fetched"]
            result["new"] += stats["new"]
            result["skipped"] += stats["skipped"]
        except Exception as e:
            logger.error("Failed to fetch channel %s: %s", ch["handle"], e)
            result["errors"].append({"channel": ch["handle"], "error": str(e)})

    return result


async def fetch_channel(channel: dict, since_days: int = RECENCY_DAYS) -> dict:
    """Fetch recent videos from a single channel."""
    handle = channel["handle"]
    category = channel.get("category", "general")
    channel_url = f"https://www.youtube.com/@{handle}/videos"

    # Get recent video list via yt-dlp (metadata only, fast)
    videos = _list_channel_videos(channel_url, limit=VIDEOS_PER_CHANNEL)

    stats = {"fetched": len(videos), "new": 0, "skipped": 0}
    cutoff = datetime.utcnow() - timedelta(days=since_days)

    async with db.get_db_ctx() as conn:
        for vid in videos:
            video_url = f"https://www.youtube.com/watch?v={vid['id']}"

            # Skip if already in DB
            existing = await conn.execute(
                "SELECT id FROM items WHERE url = ?", (video_url,)
            )
            if await existing.fetchone():
                stats["skipped"] += 1
                continue

            # Check recency from upload_date if available
            upload_date = vid.get("upload_date")
            if upload_date and len(upload_date) == 8:
                try:
                    vid_date = datetime.strptime(upload_date, "%Y%m%d")
                    if vid_date < cutoff:
                        stats["skipped"] += 1
                        continue
                except ValueError:
                    pass

            # Insert as pending item
            item_id = await db.insert_item(conn, url=video_url,
                                           content_type="video", category=category)
            stats["new"] += 1

        await db.update_channel_fetched(conn, channel["id"])

    return stats


async def process_pending_videos():
    """Process all pending video items — extract transcripts and summarize."""
    async with db.get_db_ctx() as conn:
        cursor = await conn.execute(
            "SELECT * FROM items WHERE status = 'pending' AND content_type = 'video' "
            "ORDER BY submitted_at DESC LIMIT 20"
        )
        pending = [dict(r) for r in await cursor.fetchall()]

    processed = 0
    for item in pending:
        try:
            await _process_video_item(item["id"], item["url"])
            processed += 1
        except Exception as e:
            logger.error("Failed to process video %s: %s", item["url"], e)
            async with db.get_db_ctx() as conn:
                await db.update_item_status(conn, item["id"], "error", str(e))

    return processed


async def _process_video_item(item_id: int, url: str):
    """Extract, classify, and summarize a single video."""
    from xtesync.services import classifier, synthesis

    async with db.get_db_ctx() as conn:
        await db.update_item_status(conn, item_id, "processing")

        # Extract content (transcript + metadata)
        result = await content.extract(url)

        # Domain-based classification fallback
        domain_type, domain_cat = classifier.classify_by_domain(url)
        content_type = domain_type or "video"
        category = domain_cat or "general"
        confidence = 0.7 if domain_cat else 0.3

        try:
            content_type, category, confidence = await classifier.classify(
                url, title=result.title, snippet=result.text[:500]
            )
        except Exception as e:
            logger.warning("AI classify failed: %s", e)

        # Save extracted content
        await db.update_item_extracted(conn, item_id,
            title=result.title,
            source_domain=result.source_domain,
            content_text=result.text,
            content_html=result.html,
            word_count=result.word_count,
            content_type=content_type,
            auto_category=category,
            auto_category_confidence=confidence,
        )

        item = await db.get_item(conn, item_id)
        if not item.get("category"):
            await db.update_item_extracted(conn, item_id, category=category)

        # Summarize (best-effort)
        try:
            synth = await synthesis.summarize_item(
                result.title or "Untitled", result.text, category, result.word_count,
            )
            await db.update_item_extracted(conn, item_id,
                summary=synth.brief, detail=synth.full_text,
            )
        except Exception as e:
            logger.warning("AI summarize failed: %s", e)
            await db.update_item_extracted(conn, item_id,
                summary=result.text[:300], detail=result.text,
            )

        # Generate EPUB
        from xtesync.services.epub_builder import build_item_epub
        item = await db.get_item(conn, item_id)
        epub_path = build_item_epub(item)
        await db.update_item_extracted(conn, item_id, full_epub_path=epub_path)

        await db.update_item_status(conn, item_id, "ready")


def _list_channel_videos(channel_url: str, limit: int = 5) -> list[dict]:
    """List recent videos from a YouTube channel via yt-dlp."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json",
             "--playlist-end", str(limit), "--no-download", channel_url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning("yt-dlp failed for %s: %s", channel_url, result.stderr[:200])
            return []

        videos = []
        for line in result.stdout.strip().split("\n"):
            if line:
                videos.append(json.loads(line))
        return videos
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.error("yt-dlp error: %s", e)
        return []
