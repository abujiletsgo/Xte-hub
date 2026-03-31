"""Pydantic models for XteSync API requests and responses."""

from __future__ import annotations

from pydantic import BaseModel, HttpUrl


# --- Request models ---

class ItemSubmit(BaseModel):
    url: str
    category: str | None = None
    content_type: str | None = None


class GenerateRequest(BaseModel):
    date: str | None = None  # YYYY-MM-DD, defaults to today


# --- Response models ---

class ClassificationResult(BaseModel):
    content_type: str
    category: str
    confidence: float


class ItemSummary(BaseModel):
    id: int
    title: str | None
    source_domain: str | None
    summary: str | None


class ClusterSummary(BaseModel):
    id: int
    headline: str
    synthesis: str | None
    detail: str | None = None
    key_facts: list[dict] | None = None
    source_agreement: str | None = None
    item_count: int
    items: list[ItemSummary] = []


class BriefingCategory(BaseModel):
    name: str
    icon: str
    clusters: list[ClusterSummary] = []
    standalone_items: list[ItemSummary] = []


class ItemResponse(BaseModel):
    id: int
    url: str
    title: str | None = None
    content_type: str | None = None
    category: str | None = None
    auto_classified: ClassificationResult | None = None
    status: str
    summary: str | None = None
    submitted_at: str | None = None
    cluster_id: int | None = None
    outputs: dict | None = None


class BriefingResponse(BaseModel):
    date: str
    total_stories: int
    categories: list[BriefingCategory]
    epub_path: str | None = None


class SyncStatus(BaseModel):
    id: int
    briefing_date: str
    epub_path: str | None
    generated_at: str | None
    synced_at: str | None


# --- Internal data structures ---

class ContentResult(BaseModel):
    title: str | None = None
    text: str = ""
    html: str = ""
    word_count: int = 0
    source_domain: str = ""


class SynthesisResult(BaseModel):
    brief: str = ""
    full_text: str = ""
    key_facts: list[dict] = []
    source_agreement: str = ""


CATEGORY_ICONS = {
    "korean_news": "🇰🇷",
    "world_news": "🌍",
    "ai": "🤖",
    "tech": "⚡",
    "economics": "📊",
    "politics": "🏛",
    "crypto": "₿",
    "science": "🔬",
    "podcasts": "🎧",
    "travel": "✈",
    "lifestyle": "🌿",
    "general": "📰",
}

CATEGORY_ORDER = [
    "korean_news",
    "world_news",
    "ai",
    "tech",
    "economics",
    "politics",
    "crypto",
    "science",
    "podcasts",
    "travel",
    "lifestyle",
    "general",
]
