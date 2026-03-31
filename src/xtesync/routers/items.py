"""API router for content items - submit URLs, list items."""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

from xtesync import database as db
from xtesync.models import ItemResponse, ItemSubmit
from xtesync.services import classifier, content, synthesis

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/items", tags=["items"])


async def _process_item(item_id: int, url: str):
    """Background task: extract, classify, and summarize a URL."""
    async with db.get_db_ctx() as conn:
        try:
            await db.update_item_status(conn, item_id, "processing")

            # Step 1: Extract content (no AI needed)
            result = await content.extract(url)

            # Step 2: Classify — domain heuristics first, AI as best-effort
            domain_type, domain_cat = classifier.classify_by_domain(url)
            content_type = domain_type or "article"
            category = domain_cat or "general"
            confidence = 0.7 if domain_cat else 0.3

            try:
                content_type, category, confidence = await classifier.classify(
                    url, title=result.title, snippet=result.text[:500]
                )
            except Exception as e:
                logger.warning("AI classify failed (using domain fallback): %s", e)

            # Step 3: Save extracted content immediately
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

            # Step 4: Check for low content (possible paywall)
            if result.word_count < 200 and content_type not in ("video", "podcast"):
                await db.update_item_status(
                    conn, item_id, "error",
                    "Content too short - possible paywall or extraction failure"
                )
                return

            # Step 5: AI summarization — best-effort
            try:
                synth = await synthesis.summarize_item(
                    result.title or "Untitled",
                    result.text,
                    category,
                    result.word_count,
                )
                await db.update_item_extracted(conn, item_id,
                    summary=synth.brief,
                    detail=synth.full_text,
                )
            except Exception as e:
                logger.warning("AI summarize failed (using text excerpt): %s", e)
                await db.update_item_extracted(conn, item_id,
                    summary=result.text[:300],
                    detail=result.text,
                )

            # Step 6: Generate standalone full EPUB
            from xtesync.services.epub_builder import build_item_epub
            item = await db.get_item(conn, item_id)
            epub_path = build_item_epub(item)
            await db.update_item_extracted(conn, item_id, full_epub_path=epub_path)

            await db.update_item_status(conn, item_id, "ready")

        except Exception as e:
            await db.update_item_status(conn, item_id, "error", str(e))


@router.post("/url", response_model=ItemResponse)
async def submit_url(body: ItemSubmit, background_tasks: BackgroundTasks):
    """Submit a URL for processing. Returns immediately, processes in background."""
    async with db.get_db_ctx() as conn:
        item_id = await db.insert_item(
            conn,
            url=body.url,
            content_type=body.content_type or "article",
            category=body.category,
        )
        item = await db.get_item(conn, item_id)

    # Kick off background processing
    background_tasks.add_task(_process_item, item_id, body.url)

    return _item_to_response(item)


@router.get("", response_model=list[ItemResponse])
async def list_items(
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    """List items with optional filters."""
    async with db.get_db_ctx() as conn:
        items = await db.get_items(conn, status=status, category=category, limit=limit, offset=offset)
    return [_item_to_response(i) for i in items]


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int):
    """Get a single item by ID."""
    async with db.get_db_ctx() as conn:
        item = await db.get_item(conn, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return _item_to_response(item)


def _item_to_response(item: dict) -> ItemResponse:
    auto_classified = None
    if item.get("auto_category"):
        from xtesync.models import ClassificationResult
        auto_classified = ClassificationResult(
            content_type=item.get("content_type") or "article",
            category=item["auto_category"],
            confidence=item.get("auto_category_confidence") or 0.0,
        )

    outputs = None
    if item.get("summary") or item.get("full_epub_path"):
        outputs = {
            "summary": {
                "status": "ready" if item.get("summary") else "pending",
                "word_count": len(item["summary"].split()) if item.get("summary") else 0,
            },
            "full": {
                "status": "ready" if item.get("full_epub_path") else "processing",
                "epub_path": item.get("full_epub_path"),
            },
        }

    return ItemResponse(
        id=item["id"],
        url=item["url"],
        title=item.get("title"),
        content_type=item.get("content_type"),
        category=item.get("category"),
        auto_classified=auto_classified,
        status=item["status"],
        summary=item.get("summary"),
        submitted_at=item.get("submitted_at"),
        cluster_id=item.get("cluster_id"),
        outputs=outputs,
    )
