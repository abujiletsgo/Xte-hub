"""News scraper — Korean and world news from RSS feeds and article extraction."""

import logging
from datetime import datetime, timedelta

import feedparser
import httpx

from xtesync import database as db
from xtesync.services import content

logger = logging.getLogger(__name__)

# ── Korean news: politics, economy, law only. No sports, entertainment, world. ──
# Use section-specific RSS feeds, not the firehose.
KOREAN_FEEDS = {
    # Politics / government
    "연합뉴스 정치": "https://www.yna.co.kr/rss/politics.xml",
    # Economy / business
    "연합뉴스 경제": "https://www.yna.co.kr/rss/economy.xml",
    "한국경제": "https://www.hankyung.com/feed/all-news",
}

# Keywords to KEEP for Korean news (filter out irrelevant articles)
KOREAN_KEYWORDS_INCLUDE = [
    "정치", "경제", "법", "국회", "대통령", "정부", "정책", "예산", "세금", "금리",
    "부동산", "주택", "물가", "고용", "실업", "수출", "무역", "규제", "법안", "개정",
    "검찰", "법원", "헌법", "선거", "여당", "야당", "장관", "차관", "총리",
    "기획재정", "한국은행", "금융위", "공정위", "산업통상", "중소벤처",
]
# Keywords to EXCLUDE
KOREAN_KEYWORDS_EXCLUDE = [
    "스포츠", "야구", "축구", "농구", "골프", "올림픽", "KBO", "K리그",
    "연예", "아이돌", "드라마", "영화", "K-pop", "웹툰", "방송",
]

# ── World news sources (English) ──
WORLD_FEEDS = {
    "Reuters": "https://feeds.reuters.com/reuters/topNews",
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "AP News": "https://rsshub.app/apnews/topics/apf-topnews",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}

FETCH_TIMEOUT = 15.0
MAX_ARTICLES_PER_FEED = 3  # fewer per feed, quality over quantity
RECENCY_HOURS = 24


async def fetch_korean_news(max_per_feed: int = MAX_ARTICLES_PER_FEED) -> dict:
    """Fetch recent Korean news articles. Returns {new, skipped, errors}."""
    return await _fetch_feeds(KOREAN_FEEDS, "korean_news", max_per_feed)


async def fetch_world_news(max_per_feed: int = MAX_ARTICLES_PER_FEED) -> dict:
    """Fetch recent world news articles. Returns {new, skipped, errors}."""
    return await _fetch_feeds(WORLD_FEEDS, "world_news", max_per_feed)


async def fetch_all_news() -> dict:
    """Fetch both Korean and world news."""
    kr = await fetch_korean_news()
    world = await fetch_world_news()
    return {
        "korean": kr,
        "world": world,
        "total_new": kr["new"] + world["new"],
    }


def _passes_korean_filter(title: str, summary: str) -> bool:
    """Filter Korean news: keep politics/economy/law, skip sports/entertainment."""
    text = (title + " " + summary).lower()
    # Exclude first
    for kw in KOREAN_KEYWORDS_EXCLUDE:
        if kw in text:
            return False
    # Must match at least one include keyword
    for kw in KOREAN_KEYWORDS_INCLUDE:
        if kw in text:
            return True
    # No keyword match — skip (better to be selective)
    return False


async def _fetch_feeds(feeds: dict[str, str], category: str,
                       max_per_feed: int) -> dict:
    stats = {"new": 0, "skipped": 0, "filtered": 0, "errors": []}

    for source_name, feed_url in feeds.items():
        try:
            entries = await _parse_feed(feed_url, max_per_feed * 3 if category == "korean_news" else max_per_feed)
            added_this_feed = 0
            for entry in entries:
                if added_this_feed >= max_per_feed:
                    break

                url = entry.get("link", "")
                if not url:
                    continue

                title = entry.get("title", "")
                summary = entry.get("summary", "")

                # Korean news filter
                if category == "korean_news" and not _passes_korean_filter(title, summary):
                    stats["filtered"] += 1
                    continue

                async with db.get_db_ctx() as conn:
                    existing = await conn.execute(
                        "SELECT id FROM items WHERE url = ?", (url,)
                    )
                    if await existing.fetchone():
                        stats["skipped"] += 1
                        continue

                    item_id = await db.insert_item(
                        conn, url=url, content_type="article", category=category
                    )

                    if title:
                        await db.update_item_extracted(
                            conn, item_id,
                            title=title,
                            source_domain=source_name,
                        )

                    stats["new"] += 1
                    added_this_feed += 1

        except Exception as e:
            logger.warning("Feed fetch failed for %s: %s", source_name, e)
            stats["errors"].append({"source": source_name, "error": str(e)})

    return stats


async def _parse_feed(feed_url: str, max_entries: int) -> list[dict]:
    """Fetch and parse an RSS/Atom feed."""
    async with httpx.AsyncClient(
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": "XteSync/0.1"},
        follow_redirects=True,
    ) as client:
        resp = await client.get(feed_url)
        resp.raise_for_status()

    feed = feedparser.parse(resp.text)
    entries = []

    for entry in feed.entries[:max_entries]:
        entries.append({
            "title": entry.get("title", ""),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
            "summary": entry.get("summary", ""),
        })

    return entries


async def process_pending_news():
    """Process all pending news articles — extract and summarize."""
    async with db.get_db_ctx() as conn:
        cursor = await conn.execute(
            "SELECT * FROM items WHERE status = 'pending' "
            "AND content_type = 'article' "
            "AND category IN ('korean_news', 'world_news') "
            "ORDER BY submitted_at DESC LIMIT 30"
        )
        pending = [dict(r) for r in await cursor.fetchall()]

    processed = 0
    for item in pending:
        try:
            await _process_news_item(item)
            processed += 1
        except Exception as e:
            logger.error("Failed to process news %s: %s", item["url"], e)
            async with db.get_db_ctx() as conn:
                await db.update_item_status(conn, item["id"], "error", str(e))

    return processed


async def _process_news_item(item: dict):
    """Extract and summarize a single news article."""
    from xtesync.services import synthesis

    item_id = item["id"]
    url = item["url"]
    category = item.get("category", "world_news")

    async with db.get_db_ctx() as conn:
        await db.update_item_status(conn, item_id, "processing")

        # Extract article content
        result = await content.extract(url)

        # Save extracted content
        await db.update_item_extracted(conn, item_id,
            title=result.title or item.get("title"),
            source_domain=result.source_domain or item.get("source_domain"),
            content_text=result.text,
            content_html=result.html,
            word_count=result.word_count,
        )

        # Skip very short content (paywall / extraction failure)
        if result.word_count < 100:
            await db.update_item_status(conn, item_id, "error",
                                        "Too short — possible paywall")
            return

        # Summarize — Korean news gets Korean prompts, world gets English
        try:
            synth = await synthesis.summarize_item(
                result.title or "Untitled",
                result.text,
                category,
                result.word_count,
            )
            await db.update_item_extracted(conn, item_id,
                summary=synth.brief, detail=synth.full_text,
            )
        except Exception as e:
            logger.warning("AI summarize failed: %s", e)
            await db.update_item_extracted(conn, item_id,
                summary=result.text[:400], detail=result.text,
            )

        await db.update_item_status(conn, item_id, "ready")
