"""URL and content classifier - auto-detects content type and category."""

import json
import os
from urllib.parse import urlparse

from google import genai

# Domain → content_type mappings
CONTENT_TYPE_DOMAINS = {
    "youtube.com": "video",
    "www.youtube.com": "video",
    "youtu.be": "video",
    "vimeo.com": "video",
    "arxiv.org": "paper",
    "doi.org": "paper",
    "scholar.google.com": "paper",
    "podcasts.apple.com": "podcast",
    "open.spotify.com": "podcast",
    "overcast.fm": "podcast",
}

# Domain → category hints
CATEGORY_HINTS = {
    "techcrunch.com": "tech",
    "theverge.com": "tech",
    "arstechnica.com": "tech",
    "wired.com": "tech",
    "9to5mac.com": "tech",
    "reuters.com": "general",
    "bloomberg.com": "economics",
    "wsj.com": "economics",
    "ft.com": "economics",
    "cnbc.com": "economics",
    "coindesk.com": "crypto",
    "cointelegraph.com": "crypto",
    "decrypt.co": "crypto",
    "nature.com": "science",
    "sciencedaily.com": "science",
    "newscientist.com": "science",
    "politico.com": "politics",
    "thehill.com": "politics",
    "bbc.com": "general",
    "cnn.com": "general",
    "nytimes.com": "general",
}

VALID_CATEGORIES = [
    "tech", "economics", "politics", "crypto",
    "science", "videos", "podcasts", "travel",
    "lifestyle", "general",
]

VALID_CONTENT_TYPES = [
    "article", "news", "video", "podcast",
    "paper", "essay", "reference",
]


def classify_by_domain(url: str) -> tuple[str | None, str | None]:
    """Quick classification based on URL domain. Returns (content_type, category)."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower().removeprefix("www.")

    content_type = CONTENT_TYPE_DOMAINS.get(parsed.netloc.lower())
    if not content_type:
        content_type = CONTENT_TYPE_DOMAINS.get(domain)

    # Map video/podcast content types to their categories
    if content_type == "video":
        return content_type, "videos"
    if content_type == "podcast":
        return content_type, "podcasts"
    if content_type == "paper":
        return content_type, "science"

    category = CATEGORY_HINTS.get(domain)

    # Check path for PDF
    if parsed.path.lower().endswith(".pdf"):
        content_type = "paper"
        category = category or "science"

    return content_type, category


async def classify_with_ai(title: str, snippet: str, url: str) -> tuple[str, str, float]:
    """Use Gemini to classify content. Returns (content_type, category, confidence)."""
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    prompt = f"""Classify this content into exactly one content_type and one category.

URL: {url}
Title: {title}
Snippet (first 500 chars): {snippet[:500]}

content_type must be one of: {', '.join(VALID_CONTENT_TYPES)}
category must be one of: {', '.join(VALID_CATEGORIES)}

Respond with JSON only:
{{"content_type": "...", "category": "...", "confidence": 0.0-1.0}}"""

    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )

    try:
        text = response.text.strip()
        # Extract JSON if wrapped in markdown code block
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        result = json.loads(text)
        return (
            result.get("content_type", "article"),
            result.get("category", "general"),
            result.get("confidence", 0.5),
        )
    except (json.JSONDecodeError, IndexError, KeyError):
        return "article", "general", 0.3


async def classify(url: str, title: str | None = None, snippet: str | None = None) -> tuple[str, str, float]:
    """
    Classify a URL into content_type and category.
    Returns (content_type, category, confidence).
    Uses domain heuristics first, falls back to AI.
    """
    content_type, category = classify_by_domain(url)

    # If both are known from domain, high confidence
    if content_type and category:
        return content_type, category, 0.95

    # If we have partial info, try AI for the rest
    if title or snippet:
        ai_type, ai_cat, confidence = await classify_with_ai(
            title or "", snippet or "", url
        )
        return (
            content_type or ai_type,
            category or ai_cat,
            confidence if not (content_type or category) else 0.85,
        )

    # Fallback
    return content_type or "article", category or "general", 0.3
