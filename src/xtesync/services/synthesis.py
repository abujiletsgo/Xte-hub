"""AI synthesis service - clustering, summarization, and fact-checking."""

import json
import re

import anthropic

from xtesync.models import SynthesisResult

MODEL = "claude-sonnet-4-6"


async def summarize_item(title: str, content_text: str, category: str, word_count: int) -> SynthesisResult:
    """Generate summary and in-depth detail for a single item."""
    # Short content: summary only, full text as detail
    if word_count < 500:
        client = anthropic.AsyncAnthropic()
        message = await client.messages.create(
            model=MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": f"""Summarize this {category} article in 2-3 sentences.
Title: {title}
Content: {content_text[:3000]}

Respond with JSON: {{"summary": "...", "key_facts": [{{"marker": "✓", "text": "..."}}]}}"""}],
        )
        try:
            text = _extract_json(message.content[0].text)
            data = json.loads(text)
            return SynthesisResult(
                brief=data.get("summary", content_text[:200]),
                full_text=content_text,
                key_facts=data.get("key_facts", []),
            )
        except (json.JSONDecodeError, IndexError):
            return SynthesisResult(brief=content_text[:200], full_text=content_text)

    client = anthropic.AsyncAnthropic()
    message = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": f"""You are creating content for an e-ink reading device briefing.
Given this article, create TWO versions:

Title: {title}
Category: {category}
Content:
{content_text[:8000]}

Respond with JSON:
{{
    "summary": "2-3 sentence summary with key facts. Be specific with numbers and names.",
    "detail": "Full restructured article in 3-8 paragraphs. Use clear section headers. Include all important details, quotes, and data points. Write in clean, readable prose.",
    "key_facts": [
        {{"marker": "✓", "text": "confirmed fact"}},
        {{"marker": "📊", "text": "key data point"}}
    ]
}}"""}],
    )

    try:
        text = _extract_json(message.content[0].text)
        data = json.loads(text)
        return SynthesisResult(
            brief=data.get("summary", ""),
            full_text=data.get("detail", content_text),
            key_facts=data.get("key_facts", []),
        )
    except (json.JSONDecodeError, IndexError):
        return SynthesisResult(
            brief=content_text[:300],
            full_text=content_text,
        )


async def cluster_stories(items: list[dict]) -> list[dict]:
    """Group related items into story clusters using Claude.

    Returns list of clusters:
    [{"headline": "...", "category": "...", "item_ids": [1, 2, 3]}, ...]
    """
    if not items:
        return []

    if len(items) == 1:
        return [{
            "headline": items[0].get("title", "Untitled"),
            "category": items[0].get("category") or items[0].get("auto_category") or "general",
            "item_ids": [items[0]["id"]],
        }]

    # Build item list for Claude
    item_descriptions = []
    for item in items:
        cat = item.get("category") or item.get("auto_category") or "general"
        desc = f"ID:{item['id']} | Category:{cat} | Title: {item.get('title', 'Untitled')}"
        if item.get("summary"):
            desc += f" | Summary: {item['summary'][:150]}"
        item_descriptions.append(desc)

    items_text = "\n".join(item_descriptions)

    client = anthropic.AsyncAnthropic()

    # For large batches, chunk
    if len(items) > 20:
        return await _cluster_large_batch(items, client)

    message = await client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": f"""Group these news items into story clusters. Items about the same event/topic should be grouped together.

ITEMS:
{items_text}

Rules:
- Group items that cover the SAME event or topic
- Items from different categories should NOT be grouped (e.g., a tech item and an economics item)
- Single-source stories should be their own cluster
- Generate a clear headline for each cluster

Respond with JSON array:
[
    {{
        "headline": "Clear, factual headline for this story",
        "category": "tech|economics|politics|crypto|science|videos|podcasts|travel|lifestyle|general",
        "item_ids": [1, 2, 3]
    }}
]"""}],
    )

    try:
        text = _extract_json(message.content[0].text)
        clusters = json.loads(text)
        # Validate item IDs exist
        valid_ids = {item["id"] for item in items}
        for cluster in clusters:
            cluster["item_ids"] = [id for id in cluster["item_ids"] if id in valid_ids]
        return [c for c in clusters if c["item_ids"]]
    except (json.JSONDecodeError, IndexError):
        # Fallback: each item is its own cluster
        return [{
            "headline": item.get("title", "Untitled"),
            "category": item.get("category") or item.get("auto_category") or "general",
            "item_ids": [item["id"]],
        } for item in items]


async def _cluster_large_batch(items: list[dict], client: anthropic.AsyncAnthropic) -> list[dict]:
    """Handle batches > 20 items by chunking."""
    chunk_size = 20
    all_clusters = []
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        chunk_clusters = await cluster_stories(chunk)
        all_clusters.extend(chunk_clusters)
    return all_clusters


SYNTHESIS_PROMPT = """You are a senior news editor creating a morning briefing.
You have {n} sources reporting on the same story.

SOURCES:
{sources_text}

Create a synthesized briefing entry following this exact JSON format:
{{
    "headline": "Clear, factual headline",
    "synthesis_brief": "3-5 sentence summary combining ALL unique information from all sources. Be specific with numbers, names, dates.",
    "synthesis_full": "Full in-depth article (5-10 paragraphs) that restructures and combines all source material. Use section headers. Include all important details, quotes, and data.",
    "key_facts": [
        {{"marker": "✓", "text": "fact agreed by multiple sources"}},
        {{"marker": "⚠", "text": "conflicting claim - Source A says X, Source B says Y"}},
        {{"marker": "❓", "text": "claim from single source only"}},
        {{"marker": "📊", "text": "verifiable number or statistic"}},
        {{"marker": "🔗", "text": "from official/primary source"}}
    ],
    "source_agreement": "Brief assessment: Do sources agree? What are the key points of disagreement?"
}}

Rules:
- Combine information, don't repeat
- Flag contradictions explicitly with ⚠
- Mark single-source claims with ❓
- Include specific numbers and dates
- Be factual, neutral, no editorializing
- If a primary source exists (official statement), note with 🔗"""


async def synthesize_cluster(cluster_items: list[dict]) -> SynthesisResult:
    """Synthesize multiple sources about the same story with fact-checking."""
    if len(cluster_items) == 1:
        item = cluster_items[0]
        return SynthesisResult(
            brief=item.get("summary", ""),
            full_text=item.get("detail", item.get("content_text", "")),
            key_facts=[{"marker": "❓", "text": "Single source report"}],
            source_agreement="Single source - not cross-referenced",
        )

    # Build sources text
    sources_parts = []
    for i, item in enumerate(cluster_items, 1):
        source = item.get("source_domain", "Unknown")
        title = item.get("title", "Untitled")
        content = item.get("content_text", item.get("summary", ""))
        sources_parts.append(
            f"--- SOURCE {i}: {source} ---\n"
            f"Title: {title}\n"
            f"Content:\n{content[:3000]}\n"
        )

    sources_text = "\n".join(sources_parts)
    prompt = SYNTHESIS_PROMPT.format(n=len(cluster_items), sources_text=sources_text)

    client = anthropic.AsyncAnthropic()
    message = await client.messages.create(
        model=MODEL,
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )

    try:
        text = _extract_json(message.content[0].text)
        data = json.loads(text)
        return SynthesisResult(
            brief=data.get("synthesis_brief", ""),
            full_text=data.get("synthesis_full", ""),
            key_facts=data.get("key_facts", []),
            source_agreement=data.get("source_agreement", ""),
        )
    except (json.JSONDecodeError, IndexError):
        # Fallback: concatenate summaries
        combined = "\n\n".join(
            f"From {item.get('source_domain', 'Unknown')}: {item.get('summary', '')}"
            for item in cluster_items
        )
        return SynthesisResult(
            brief=combined[:500],
            full_text=combined,
            key_facts=[],
            source_agreement="Synthesis failed - raw summaries shown",
        )


def _extract_json(text: str) -> str:
    """Extract JSON from a response that might contain markdown code blocks."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for part in parts[1::2]:  # odd-indexed parts are inside code blocks
            cleaned = part.strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
            if cleaned.startswith(("{", "[")):
                return cleaned
    # Try to find JSON directly
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        start = text.find(start_char)
        end = text.rfind(end_char)
        if start != -1 and end != -1 and end > start:
            return text[start:end + 1]
    return text
