"""API router for YouTube channel subscriptions and feed management."""

import json
import logging
import re
import subprocess
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from xtesync import database as db
from xtesync.services import feed

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/channels", tags=["channels"])

# Known channel → category mappings for auto-categorization
CHANNEL_CATEGORIES = {
    # AI / Claude Code / LLMs
    "anthropicai": "ai", "claudeai": "ai", "aiexplained": "ai",
    "aiflux": "ai", "matthewberman": "ai", "samwitteveenai": "ai",
    "daveebbelaar": "ai", "aicodingassistant": "ai", "indydevdan": "ai",
    "coreyms": "ai", "techwithtim": "ai", "sentdex": "ai",
    "yanaborgnern": "ai", "fireship": "ai", "theaigrid": "ai",
    "aibreakfast": "ai", "bycloud": "ai", "airevolutionx": "ai",
    "twosetai": "ai", "whatsai": "ai", "wesmckinney": "ai",
    # Tech
    "mkbhd": "tech", "linustechtips": "tech", "austinnotduncan": "tech",
    "mrwhosetheboss": "tech", "unboxtherapy": "tech", "dave2d": "tech",
    "theverge": "tech", "jerryrigeverything": "tech", "ijustine": "tech",
    # Economics / Finance
    "patrickboyle": "economics", "plainbagel": "economics",
    "economicsexplained": "economics", "tldr news": "economics",
    "moneyandmacro": "economics", "coldfusion": "economics",
    # Crypto
    "coinbureau": "crypto", "whiteboard crypto": "crypto",
    # Science
    "veritasium": "science", "kurzgesagt": "science", "smartereveryday": "science",
    "3blue1brown": "science", "minutephysics": "science",
    # Podcasts
    "lexfridman": "podcasts", "joerogan": "podcasts", "hubermanlab": "podcasts",
    "allaborgnern": "podcasts", "dwarkeshpatel": "podcasts",
    "podcastnotes": "podcasts",
    # General
    "polymatter": "general", "wendover": "general", "johnneyharris": "general",
    "vox": "general", "reallifelore": "general",
}

# Keywords in channel name/description for auto-detect
CATEGORY_KEYWORDS = {
    "ai": ["ai", "artificial intelligence", "llm", "gpt", "claude", "machine learning",
           "deep learning", "neural", "chatgpt", "copilot", "cursor", "coding assistant"],
    "tech": ["tech", "gadget", "review", "unbox", "smartphone", "laptop", "software"],
    "economics": ["economics", "finance", "market", "investing", "economy", "money", "stock"],
    "crypto": ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "web3"],
    "science": ["science", "physics", "math", "biology", "chemistry", "space", "engineering"],
    "podcasts": ["podcast", "interview", "conversation", "show", "episode"],
}


class AddChannel(BaseModel):
    handle: str
    name: str | None = None
    category: str = "auto"


class AddBatch(BaseModel):
    urls: list[str]


def _parse_handle(raw: str) -> str:
    """Extract YouTube handle from URL or raw input."""
    raw = raw.strip()
    # Full URL: https://youtube.com/@handle or /channel/... or /c/...
    if "youtube.com" in raw or "youtu.be" in raw:
        parsed = urlparse(raw)
        path = parsed.path.strip("/")
        # /@handle
        if path.startswith("@"):
            return path.split("/")[0].lstrip("@")
        # /c/name or /channel/ID or /user/name
        parts = path.split("/")
        if len(parts) >= 2 and parts[0] in ("c", "channel", "user"):
            return parts[1]
        if parts[0].startswith("@"):
            return parts[0].lstrip("@")
        return parts[0] if parts[0] else raw
    # Just a handle with or without @
    return raw.lstrip("@").split("/")[0]


def _auto_categorize(handle: str) -> str:
    """Auto-detect category from handle name."""
    key = handle.lower().replace("-", "").replace("_", "").replace(" ", "")
    if key in CHANNEL_CATEGORIES:
        return CHANNEL_CATEGORIES[key]

    # Keyword matching on handle
    handle_lower = handle.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in handle_lower:
                return cat
    return "general"


def _get_channel_name(handle: str) -> str | None:
    """Try to get channel display name via yt-dlp."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--playlist-end", "1",
             "--flat-playlist", "--no-download",
             f"https://www.youtube.com/@{handle}/videos"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout.strip().split("\n")[0])
            return data.get("channel") or data.get("uploader")
    except Exception:
        pass
    return None


@router.post("")
async def add_channel(body: AddChannel):
    """Subscribe to a YouTube channel. Accepts handles or full URLs."""
    handle = _parse_handle(body.handle)
    if not handle:
        raise HTTPException(status_code=400, detail="Could not parse channel handle")

    category = body.category if body.category != "auto" else _auto_categorize(handle)
    name = body.name or _get_channel_name(handle)

    async with db.get_db_ctx() as conn:
        channel_id = await db.add_channel(conn, handle=handle, name=name, category=category)
        ch = await conn.execute("SELECT * FROM channels WHERE id = ?", (channel_id,))
        row = await ch.fetchone()

    return dict(row)


@router.post("/batch")
async def add_channels_batch(body: AddBatch):
    """Add multiple channels at once from a list of URLs/handles."""
    results = []
    for raw in body.urls:
        raw = raw.strip()
        if not raw:
            continue
        handle = _parse_handle(raw)
        if not handle:
            results.append({"input": raw, "error": "Could not parse"})
            continue

        category = _auto_categorize(handle)
        name = _get_channel_name(handle)

        async with db.get_db_ctx() as conn:
            channel_id = await db.add_channel(conn, handle=handle, name=name, category=category)

        results.append({
            "input": raw, "handle": handle, "name": name,
            "category": category, "id": channel_id,
        })

    return {"added": len([r for r in results if "id" in r]), "results": results}


@router.get("")
async def list_channels():
    async with db.get_db_ctx() as conn:
        return await db.get_channels(conn, enabled_only=True)


@router.delete("/{channel_id}")
async def remove_channel(channel_id: int):
    async with db.get_db_ctx() as conn:
        await db.remove_channel(conn, channel_id)
    return {"status": "removed"}


@router.post("/fetch")
async def fetch_new_videos(background_tasks: BackgroundTasks):
    background_tasks.add_task(_fetch_and_process)
    return {"status": "started"}


async def _fetch_and_process():
    try:
        fetch_result = await feed.fetch_all_channels()
        logger.info("Feed fetch: %s", fetch_result)
        if fetch_result["new"] > 0:
            await feed.process_pending_videos()
    except Exception as e:
        logger.error("Feed fetch/process failed: %s", e)


@router.post("/fetch-and-brief")
async def fetch_and_generate_briefing(background_tasks: BackgroundTasks):
    background_tasks.add_task(_full_pipeline)
    return {"status": "started"}


async def _full_pipeline():
    from datetime import date
    from xtesync.models import SynthesisResult
    from xtesync.services import epub_builder, news, sync, synthesis

    try:
        # 1a. Fetch YouTube channels
        fetch_result = await feed.fetch_all_channels()
        logger.info("YouTube fetch: %s", fetch_result)

        # 1b. Fetch Korean + world news
        news_result = await news.fetch_all_news()
        logger.info("News fetch: %s", news_result)

        # 2a. Process YouTube videos
        if fetch_result["new"] > 0:
            await feed.process_pending_videos()

        # 2b. Process news articles
        if news_result["total_new"] > 0:
            await news.process_pending_news()

        today = date.today().isoformat()

        async with db.get_db_ctx() as conn:
            items = await db.get_unprocessed_items_for_briefing(conn, since_hours=72)
            if not items:
                logger.info("No ready items for briefing")
                return

            try:
                cluster_groups = await synthesis.cluster_stories(items)
            except Exception:
                cluster_groups = [{
                    "headline": item.get("title", "Untitled"),
                    "category": item.get("category") or item.get("auto_category") or "general",
                    "item_ids": [item["id"]],
                } for item in items]

            items_by_id = {item["id"]: item for item in items}
            categories_map: dict[str, list[dict]] = {}

            for cg in cluster_groups:
                cluster_items = [items_by_id[i] for i in cg["item_ids"] if i in items_by_id]
                if not cluster_items:
                    continue

                slug = _slugify(cg["headline"]) + f"-{today}"

                try:
                    synth = await synthesis.synthesize_cluster(cluster_items)
                except Exception:
                    synth = SynthesisResult(
                        brief=cluster_items[0].get("summary", ""),
                        full_text=cluster_items[0].get("detail",
                                  cluster_items[0].get("content_text", "")),
                    )

                cluster_id = await db.create_cluster(conn,
                    slug=slug, headline=cg["headline"], category=cg["category"],
                    synthesis=synth.brief, key_facts=synth.key_facts,
                    source_agreement=synth.source_agreement,
                )
                for item in cluster_items:
                    await db.add_item_to_cluster(conn, cluster_id, item["id"])

                sources = list({i.get("source_domain", "Unknown") for i in cluster_items})
                cat = cg["category"]
                if cat not in categories_map:
                    categories_map[cat] = []
                categories_map[cat].append({
                    "headline": cg["headline"],
                    "category": cat,
                    "synthesis_brief": synth.brief,
                    "synthesis_full": synth.full_text,
                    "key_facts": synth.key_facts,
                    "source_agreement": synth.source_agreement,
                    "sources": sources,
                })

            epub_path = epub_builder.build_briefing_epub(today, categories_map)
            all_ids = [item["id"] for item in items]
            await sync.mark_generated(conn, today, epub_path, all_ids)

        logger.info("Briefing generated: %s", epub_path)

    except Exception as e:
        logger.error("Full pipeline failed: %s", e)


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:60].strip("-")
