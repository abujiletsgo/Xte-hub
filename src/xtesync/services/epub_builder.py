"""EPUB builder for XteSync - generates three-layer briefing EPUBs for e-ink."""

import html
import re
from datetime import datetime
from pathlib import Path

from ebooklib import epub

from xtesync.models import CATEGORY_ICONS, CATEGORY_ORDER

DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "content"

# E-ink optimized CSS
EINK_CSS = """
/* === XteSync E-Ink Stylesheet === */

body {
    font-family: "Bookerly", "Literata", Georgia, serif;
    font-size: 1em;
    line-height: 1.6;
    margin: 1em;
    color: #000;
    background: #fff;
}

/* Cover page */
.cover-page {
    text-align: center;
    padding-top: 3em;
}

.cover-page h1 {
    font-size: 1.6em;
    margin-bottom: 0.3em;
}

.cover-page .date {
    font-size: 1.1em;
    margin-bottom: 1em;
}

.cover-page .stats {
    font-size: 0.9em;
    color: #555;
    margin-bottom: 2em;
}

.cover-page .nav-instructions {
    font-size: 0.85em;
    color: #777;
    border-top: 1px solid #ccc;
    padding-top: 1em;
    margin-top: 2em;
}

/* Summary pages - scannable, dense */
.summary-page h1 {
    font-size: 1.3em;
    margin-bottom: 0.8em;
    border-bottom: 1px solid #666;
    padding-bottom: 0.4em;
}

.story-summary {
    margin-bottom: 1.2em;
    padding-bottom: 0.8em;
    border-bottom: 1px dotted #ccc;
}

.story-summary:last-of-type {
    border-bottom: none;
}

.story-summary h3 {
    font-size: 1em;
    font-weight: bold;
    margin-bottom: 0.2em;
}

.story-summary p {
    font-size: 0.95em;
    line-height: 1.4;
    margin-bottom: 0.15em;
}

.fact {
    font-size: 0.85em;
    padding-left: 1em;
    color: #444;
    margin-bottom: 0.1em;
}

.sources {
    font-size: 0.8em;
    color: #888;
    font-style: italic;
    margin-top: 0.3em;
}

.nav-hint {
    font-size: 0.8em;
    text-align: center;
    color: #aaa;
    margin-top: 1.2em;
    font-style: italic;
}

/* Detail pages - comfortable long-form reading */
.detail-section {
    page-break-before: always;
}

.detail-section h2 {
    font-size: 1.2em;
    margin-bottom: 0.8em;
    margin-top: 1em;
}

.detail-section h3 {
    font-size: 1.05em;
    margin-bottom: 0.5em;
    margin-top: 0.8em;
}

.detail-section p {
    font-size: 1em;
    line-height: 1.5;
    margin-bottom: 0.6em;
    text-align: justify;
}

.detail-section .source-attribution {
    font-size: 0.85em;
    color: #666;
    font-style: italic;
    border-top: 1px solid #ccc;
    padding-top: 0.5em;
    margin-top: 1.5em;
}

/* Fact check styling */
.fact-check-note {
    border-left: 3px solid #666;
    padding-left: 0.8em;
    margin: 0.8em 0;
    font-size: 0.9em;
}

.agreement-note {
    background: #f0f0f0;
    padding: 0.6em;
    margin: 0.8em 0;
    font-size: 0.9em;
}
"""


def build_briefing_epub(
    date: str,
    categories: dict[str, list[dict]],
    output_dir: str | None = None,
) -> str:
    """
    Build a daily briefing EPUB with chapter-per-category structure.

    Args:
        date: YYYY-MM-DD format date string
        categories: dict mapping category name to list of cluster dicts.
            Each cluster dict has: headline, synthesis_brief, synthesis_full,
            key_facts, source_agreement, sources (list of source_domain strings),
            items (list of item dicts with title, summary, detail, source_domain)
        output_dir: Override output directory

    Returns:
        Path to the generated EPUB file.
    """
    book = epub.EpubBook()

    # Metadata
    dt = datetime.strptime(date, "%Y-%m-%d")
    display_date = dt.strftime("%B %d, %Y")
    book.set_identifier(f"xtesync-briefing-{date}")
    book.set_title(f"Daily Briefing — {display_date}")
    book.set_language("en")
    book.add_author("XteSync")

    # Add CSS
    css = epub.EpubItem(
        uid="eink_css",
        file_name="style/eink.css",
        media_type="text/css",
        content=EINK_CSS.encode("utf-8"),
    )
    book.add_item(css)

    spine = ["nav"]
    toc = []
    chapters = []

    # Count stories
    total_stories = sum(len(clusters) for clusters in categories.values())
    active_categories = [c for c in CATEGORY_ORDER if c in categories and categories[c]]

    # Chapter 0: Cover page
    cover = _build_cover_chapter(date, display_date, total_stories, active_categories, css)
    book.add_item(cover)
    spine.append(cover)
    chapters.append(cover)

    # One chapter per category
    for idx, cat_name in enumerate(active_categories, 1):
        clusters = categories[cat_name]
        icon = CATEGORY_ICONS.get(cat_name, "📰")
        chapter = _build_category_chapter(idx, cat_name, icon, clusters, css)
        book.add_item(chapter)
        spine.append(chapter)
        chapters.append(chapter)
        toc.append(epub.Link(chapter.file_name, f"{icon} {cat_name.upper()}", f"ch{idx}"))

    # Navigation
    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    # Write EPUB
    out_dir = Path(output_dir) if output_dir else DATA_DIR / "briefings"
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{date}-Briefing.epub"
    epub.write_epub(str(file_path), book)

    return str(file_path)


def build_item_epub(
    item: dict,
    output_subdir: str = "full",
) -> str:
    """Build a standalone EPUB for a single item (full version)."""
    book = epub.EpubBook()

    title = item.get("title", "Untitled")
    slug = _slugify(title)
    category = item.get("category") or item.get("auto_category") or "general"

    book.set_identifier(f"xtesync-item-{item['id']}")
    book.set_title(title)
    book.set_language("en")
    book.add_author("XteSync")

    css = epub.EpubItem(
        uid="eink_css",
        file_name="style/eink.css",
        media_type="text/css",
        content=EINK_CSS.encode("utf-8"),
    )
    book.add_item(css)

    # Single chapter with the full content
    content = item.get("detail") or item.get("content_text") or item.get("summary") or ""
    source = item.get("source_domain", "")
    url = item.get("url", "")

    chapter_html = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{_esc(title)}</title>
<link rel="stylesheet" type="text/css" href="style/eink.css"/></head>
<body>
<div class="detail-section">
<h2>{_esc(title)}</h2>
{_text_to_html(content)}
<div class="source-attribution">
<p>Source: {_esc(source)}</p>
<p><a href="{_esc(url)}">Original article</a></p>
</div>
</div>
</body></html>"""

    ch = epub.EpubHtml(
        title=title,
        file_name="content.xhtml",
        content=chapter_html.encode("utf-8"),
    )
    ch.add_item(css)
    book.add_item(ch)

    book.toc = [epub.Link("content.xhtml", title, "content")]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", ch]

    # Determine output path based on category
    out_dir = DATA_DIR / output_subdir / category.capitalize()
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"{slug}-full.epub"
    epub.write_epub(str(file_path), book)

    return str(file_path)


def _build_cover_chapter(date: str, display_date: str, total_stories: int,
                          active_categories: list[str], css) -> epub.EpubHtml:
    cat_list = ", ".join(
        f"{CATEGORY_ICONS.get(c, '📰')} {c.capitalize()}" for c in active_categories
    )
    content = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>Daily Briefing</title>
<link rel="stylesheet" type="text/css" href="style/eink.css"/></head>
<body>
<div class="cover-page">
<h1>Your Daily Briefing</h1>
<p class="date">{display_date}</p>
<p class="stats">{total_stories} stories</p>
<p class="stats">Categories: {cat_list}</p>
<div class="nav-instructions">
<p><strong>Navigation:</strong></p>
<p>Short press = next page (read details)</p>
<p>Long press = next category (skip ahead)</p>
</div>
</div>
</body></html>"""

    ch = epub.EpubHtml(
        title="Cover",
        file_name="cover.xhtml",
        content=content.encode("utf-8"),
    )
    ch.add_item(css)
    return ch


def _build_category_chapter(idx: int, cat_name: str, icon: str,
                              clusters: list[dict], css) -> epub.EpubHtml:
    """Build a chapter with summary page + in-depth pages for each cluster."""
    parts = []

    # === SUMMARY PAGE ===
    parts.append(f'<div class="summary-page">')
    parts.append(f'<h1>{icon} {cat_name.upper()}</h1>')

    for cluster in clusters:
        headline = cluster.get("headline", "Untitled Story")
        brief = cluster.get("synthesis_brief", cluster.get("brief", ""))
        key_facts = cluster.get("key_facts", [])
        sources = cluster.get("sources", [])
        source_agreement = cluster.get("source_agreement", "")

        parts.append(f'<div class="story-summary">')
        parts.append(f'<h3>&#x25A0; {_esc(headline)}</h3>')
        parts.append(f'<p>{_esc(brief)}</p>')

        # Fact-check markers
        for fact in key_facts[:5]:  # limit to 5 facts per story in summary
            marker = fact.get("marker", "✓")
            text = fact.get("text", "")
            parts.append(f'<p class="fact">{marker} {_esc(text)}</p>')

        # Source agreement note
        if source_agreement and len(sources) > 1:
            parts.append(f'<p class="fact">{_esc(source_agreement)}</p>')

        # Sources
        if sources:
            src_text = ", ".join(sources)
            parts.append(f'<p class="sources">Sources: {_esc(src_text)}</p>')

        parts.append('</div>')

    parts.append('<p class="nav-hint">[short-press for details &#x2192;]</p>')
    parts.append('</div>')

    # === IN-DEPTH PAGES ===
    for cluster in clusters:
        headline = cluster.get("headline", "Untitled Story")
        full_text = cluster.get("synthesis_full", cluster.get("full_text", ""))
        sources = cluster.get("sources", [])
        key_facts = cluster.get("key_facts", [])

        parts.append(f'<div class="detail-section">')
        parts.append(f'<h2>{_esc(headline)}</h2>')

        # Full synthesized content
        parts.append(_text_to_html(full_text))

        # Detailed fact-check section
        if key_facts:
            parts.append('<div class="fact-check-note">')
            parts.append('<h3>Fact Check</h3>')
            for fact in key_facts:
                marker = fact.get("marker", "✓")
                text = fact.get("text", "")
                parts.append(f'<p>{marker} {_esc(text)}</p>')
            parts.append('</div>')

        # Source attribution
        if sources:
            src_text = ", ".join(sources)
            parts.append(f'<div class="source-attribution">')
            parts.append(f'<p>Sources: {_esc(src_text)}</p>')
            parts.append('</div>')

        parts.append('</div>')

    body = "\n".join(parts)
    content = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{icon} {cat_name.upper()}</title>
<link rel="stylesheet" type="text/css" href="style/eink.css"/></head>
<body>
{body}
</body></html>"""

    ch = epub.EpubHtml(
        title=f"{icon} {cat_name.upper()}",
        file_name=f"ch{idx}_{cat_name}.xhtml",
        content=content.encode("utf-8"),
    )
    ch.add_item(css)
    return ch


def _esc(text: str) -> str:
    """Escape HTML entities."""
    return html.escape(str(text)) if text else ""


def _text_to_html(text: str) -> str:
    """Convert plain text (possibly with markdown-ish headers) to HTML paragraphs."""
    if not text:
        return ""

    # If it already looks like HTML, return as-is
    if "<p>" in text or "<div>" in text or "<h" in text:
        return text

    lines = text.split("\n")
    html_parts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Simple markdown header detection
        if line.startswith("### "):
            html_parts.append(f"<h3>{_esc(line[4:])}</h3>")
        elif line.startswith("## "):
            html_parts.append(f"<h3>{_esc(line[3:])}</h3>")
        elif line.startswith("# "):
            html_parts.append(f"<h2>{_esc(line[2:])}</h2>")
        elif line.startswith("- ") or line.startswith("* "):
            html_parts.append(f"<p>&#x2022; {_esc(line[2:])}</p>")
        else:
            html_parts.append(f"<p>{_esc(line)}</p>")

    return "\n".join(html_parts)


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:80].strip("-")
