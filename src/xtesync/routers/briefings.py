"""API router for daily briefings - generate and retrieve briefings."""

import logging
import re
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from xtesync import database as db
from xtesync.models import (
    CATEGORY_ICONS,
    CATEGORY_ORDER,
    BriefingCategory,
    BriefingResponse,
    ClusterSummary,
    GenerateRequest,
    ItemSummary,
    SyncStatus,
)
from xtesync.services import epub_builder, sync, synthesis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/briefings", tags=["briefings"])


@router.post("/generate", response_model=BriefingResponse)
async def generate_briefing(body: GenerateRequest | None = None):
    """Generate a daily briefing EPUB from all ready items."""
    briefing_date = (body.date if body and body.date else date.today().isoformat())

    async with db.get_db_ctx() as conn:
        # Step 1: Get all ready items from recent window
        items = await db.get_unprocessed_items_for_briefing(conn, since_hours=48)

        if not items:
            raise HTTPException(status_code=404, detail="No items available for briefing")

        # Step 2: Cluster related stories (AI best-effort, fallback: 1 item = 1 cluster)
        try:
            cluster_groups = await synthesis.cluster_stories(items)
        except Exception as e:
            logger.warning("AI clustering failed, using per-item fallback: %s", e)
            cluster_groups = [{
                "headline": item.get("title", "Untitled"),
                "category": item.get("category") or item.get("auto_category") or "general",
                "item_ids": [item["id"]],
            } for item in items]

        # Step 3: Create clusters in DB and synthesize
        items_by_id = {item["id"]: item for item in items}
        db_clusters = []

        for cg in cluster_groups:
            cluster_items = [items_by_id[iid] for iid in cg["item_ids"] if iid in items_by_id]
            if not cluster_items:
                continue

            # Generate slug
            slug = _slugify(cg["headline"]) + f"-{briefing_date}"

            # Synthesize multi-source or single-source (best-effort)
            try:
                synth = await synthesis.synthesize_cluster(cluster_items)
            except Exception as e:
                logger.warning("Synthesis failed for '%s': %s", cg["headline"], e)
                from xtesync.models import SynthesisResult
                synth = SynthesisResult(
                    brief=cluster_items[0].get("summary", ""),
                    full_text=cluster_items[0].get("detail", cluster_items[0].get("content_text", "")),
                )

            # Create cluster in DB
            cluster_id = await db.create_cluster(
                conn,
                slug=slug,
                headline=cg["headline"],
                category=cg["category"],
                synthesis=synth.brief,
                key_facts=synth.key_facts,
                source_agreement=synth.source_agreement,
            )

            # Link items to cluster
            for item in cluster_items:
                await db.add_item_to_cluster(conn, cluster_id, item["id"])

            # Collect sources
            sources = list({item.get("source_domain", "Unknown") for item in cluster_items})

            db_clusters.append({
                "id": cluster_id,
                "headline": cg["headline"],
                "category": cg["category"],
                "synthesis_brief": synth.brief,
                "synthesis_full": synth.full_text,
                "key_facts": synth.key_facts,
                "source_agreement": synth.source_agreement,
                "sources": sources,
                "items": cluster_items,
                "item_count": len(cluster_items),
            })

        # Step 4: Group by category for EPUB
        categories_map: dict[str, list[dict]] = {}
        for cluster in db_clusters:
            cat = cluster["category"]
            if cat not in categories_map:
                categories_map[cat] = []
            categories_map[cat].append(cluster)

        # Step 5: Build EPUB
        epub_path = epub_builder.build_briefing_epub(briefing_date, categories_map)

        # Step 6: Record for sync
        all_item_ids = [item["id"] for item in items]
        await sync.mark_generated(conn, briefing_date, epub_path, all_item_ids)

    # Build response
    response_categories = []
    for cat_name in CATEGORY_ORDER:
        if cat_name not in categories_map:
            continue
        cat_clusters = categories_map[cat_name]
        cluster_summaries = []
        for c in cat_clusters:
            item_summaries = [
                ItemSummary(
                    id=item["id"],
                    title=item.get("title"),
                    source_domain=item.get("source_domain"),
                    summary=item.get("summary"),
                )
                for item in c["items"]
            ]
            cluster_summaries.append(ClusterSummary(
                id=c["id"],
                headline=c["headline"],
                synthesis=c["synthesis_brief"],
                detail=c.get("synthesis_full", ""),
                key_facts=c.get("key_facts"),
                source_agreement=c.get("source_agreement"),
                item_count=c["item_count"],
                items=item_summaries,
            ))
        response_categories.append(BriefingCategory(
            name=cat_name,
            icon=CATEGORY_ICONS.get(cat_name, "📰"),
            clusters=cluster_summaries,
        ))

    return BriefingResponse(
        date=briefing_date,
        total_stories=len(db_clusters),
        categories=response_categories,
        epub_path=epub_path,
    )


@router.get("/latest", response_model=BriefingResponse)
async def get_latest_briefing():
    """Get the most recent briefing."""
    async with db.get_db_ctx() as conn:
        syncs = await db.get_pending_syncs(conn)
        # Also check synced ones
        cursor = await conn.execute(
            "SELECT * FROM sync_state ORDER BY briefing_date DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="No briefings generated yet")

        briefing = dict(row)
        return await _build_briefing_response(conn, briefing)


@router.get("/{briefing_date}", response_model=BriefingResponse)
async def get_briefing(briefing_date: str):
    """Get a specific briefing by date."""
    async with db.get_db_ctx() as conn:
        briefing = await db.get_briefing_by_date(conn, briefing_date)
        if not briefing:
            raise HTTPException(status_code=404, detail="Briefing not found")
        return await _build_briefing_response(conn, briefing)


@router.get("/{briefing_date}/download")
async def download_briefing(briefing_date: str):
    """Download the briefing EPUB file."""
    async with db.get_db_ctx() as conn:
        epub_path = await sync.get_epub_path(conn, briefing_date)

    if not epub_path or not Path(epub_path).exists():
        raise HTTPException(status_code=404, detail="Briefing EPUB not found")

    return FileResponse(
        epub_path,
        media_type="application/epub+zip",
        filename=f"{briefing_date}-Briefing.epub",
    )


# --- Sync endpoints ---

@router.get("/sync/pending", response_model=list[SyncStatus])
async def get_pending_syncs():
    """Get all briefings pending sync to device."""
    async with db.get_db_ctx() as conn:
        syncs = await sync.get_pending(conn)
    return [SyncStatus(**s) for s in syncs]


@router.post("/sync/{sync_id}/mark-synced")
async def mark_briefing_synced(sync_id: int):
    """Mark a briefing as synced to device."""
    async with db.get_db_ctx() as conn:
        await sync.mark_synced(conn, sync_id)
    return {"status": "ok"}


# --- Helpers ---

async def _build_briefing_response(conn, briefing: dict) -> BriefingResponse:
    """Build a BriefingResponse from a sync_state record."""
    import json
    item_ids = json.loads(briefing.get("item_ids_json", "[]"))

    # Get clusters for these items
    categories_map: dict[str, list] = {}
    seen_clusters = set()

    for item_id in item_ids:
        item = await db.get_item(conn, item_id)
        if not item:
            continue

        cat = item.get("category") or item.get("auto_category") or "general"

        if item.get("cluster_id") and item["cluster_id"] not in seen_clusters:
            seen_clusters.add(item["cluster_id"])
            cluster = await db.get_cluster_with_items(conn, item["cluster_id"])
            if cluster:
                if cat not in categories_map:
                    categories_map[cat] = []
                categories_map[cat].append(cluster)

    response_categories = []
    for cat_name in CATEGORY_ORDER:
        if cat_name not in categories_map:
            continue
        clusters = categories_map[cat_name]
        cluster_summaries = []
        for c in clusters:
            item_summaries = [
                ItemSummary(
                    id=i["id"],
                    title=i.get("title"),
                    source_domain=i.get("source_domain"),
                    summary=i.get("summary"),
                )
                for i in c.get("items", [])
            ]
            # Get detail text from linked items if not on cluster
            detail_text = ""
            for i in c.get("items", []):
                if i.get("detail"):
                    detail_text = i["detail"]
                    break
            cluster_summaries.append(ClusterSummary(
                id=c["id"],
                headline=c["headline"],
                synthesis=c.get("synthesis"),
                detail=detail_text,
                key_facts=c.get("key_facts"),
                source_agreement=c.get("source_agreement"),
                item_count=c.get("item_count", 0),
                items=item_summaries,
            ))
        response_categories.append(BriefingCategory(
            name=cat_name,
            icon=CATEGORY_ICONS.get(cat_name, "📰"),
            clusters=cluster_summaries,
        ))

    return BriefingResponse(
        date=briefing["briefing_date"],
        total_stories=sum(len(cat.clusters) for cat in response_categories),
        categories=response_categories,
        epub_path=briefing.get("epub_path"),
    )


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:60].strip("-")
