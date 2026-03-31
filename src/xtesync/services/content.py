"""Content extraction service - fetches URLs and extracts readable content."""

import json
import logging
import re
import subprocess
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document

from xtesync.models import ContentResult

logger = logging.getLogger(__name__)

USER_AGENT = "XteSync/0.1 (Reading Assistant)"
FETCH_TIMEOUT = 30.0
MIN_CONTENT_LENGTH = 200

VIDEO_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com", "vimeo.com"}


async def extract(url: str) -> ContentResult:
    """Fetch a URL and extract its readable content."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    base_domain = ".".join(domain.split(".")[-2:]) if "." in domain else domain

    if base_domain in {"youtube.com", "youtu.be"}:
        return await _extract_youtube(url)

    if "vimeo.com" in base_domain:
        return await _extract_video_oembed(url, domain)

    return await _extract_article(url, domain)


# ── YouTube ──────────────────────────────────────────────────

def _extract_video_id(url: str) -> str | None:
    """Extract YouTube video ID from various URL formats."""
    parsed = urlparse(url)
    if parsed.hostname in ("youtu.be",):
        return parsed.path.lstrip("/").split("/")[0]
    if parsed.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith(("/embed/", "/v/", "/shorts/")):
            return parsed.path.split("/")[2] if len(parsed.path.split("/")) > 2 else None
    return None


async def _extract_youtube(url: str) -> ContentResult:
    """Extract YouTube video with full transcript via youtube-transcript-api + yt-dlp metadata."""
    video_id = _extract_video_id(url)

    # Get metadata via yt-dlp (fast, no download)
    meta = _get_yt_metadata(url)
    title = meta.get("title", "YouTube Video")
    channel = meta.get("channel", meta.get("uploader", "Unknown"))
    description = meta.get("description", "")
    duration = meta.get("duration")
    upload_date = meta.get("upload_date", "")
    view_count = meta.get("view_count")
    like_count = meta.get("like_count")
    categories = meta.get("categories", [])
    tags = meta.get("tags", [])[:10]

    # Format duration
    dur_str = ""
    if duration:
        mins, secs = divmod(int(duration), 60)
        hrs, mins = divmod(mins, 60)
        dur_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"

    # Format date
    date_str = ""
    if upload_date and len(upload_date) == 8:
        date_str = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

    # Get transcript
    transcript_text = ""
    if video_id:
        transcript_text = _get_transcript(video_id)

    # Build structured content
    header = f"# {title}\n\nChannel: {channel}"
    if date_str:
        header += f" | Published: {date_str}"
    if dur_str:
        header += f" | Duration: {dur_str}"
    if view_count:
        header += f"\nViews: {view_count:,}"
        if like_count:
            header += f" | Likes: {like_count:,}"
    header += "\n"

    parts = [header]

    if description and len(description) > 50:
        # Trim overly long descriptions (often full of links/spam)
        desc_clean = description[:2000]
        parts.append(f"## Description\n{desc_clean}\n")

    if transcript_text:
        parts.append(f"## Transcript\n{transcript_text}")
    else:
        parts.append("[No transcript available for this video]")

    full_text = "\n".join(parts)
    word_count = len(full_text.split())

    # HTML version for EPUB
    html = f"""<div class="video-meta">
<h1>{_esc_html(title)}</h1>
<p class="channel">By <strong>{_esc_html(channel)}</strong>
{f' &middot; {date_str}' if date_str else ''}
{f' &middot; {dur_str}' if dur_str else ''}</p>
{f'<p class="stats">{view_count:,} views</p>' if view_count else ''}
<p><a href="{url}">Watch on YouTube</a></p>
</div>
<div class="transcript">
{_text_to_html_paragraphs(transcript_text) if transcript_text else '<p><em>No transcript available</em></p>'}
</div>"""

    return ContentResult(
        title=title,
        text=full_text,
        html=html,
        word_count=word_count,
        source_domain=f"youtube.com/@{channel}",
    )


def _get_yt_metadata(url: str) -> dict:
    """Get video metadata via yt-dlp without downloading."""
    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning("yt-dlp metadata failed: %s", e)
    return {}


def _get_transcript(video_id: str) -> str:
    """Get video transcript via youtube-transcript-api."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(video_id)
        lines = [entry.text for entry in transcript]
        return " ".join(lines)
    except Exception as e:
        logger.warning("Transcript fetch failed for %s: %s", video_id, e)
        return ""


# ── Generic video (oEmbed) ───────────────────────────────────

async def _extract_video_oembed(url: str, domain: str) -> ContentResult:
    """Fallback: extract video metadata via oEmbed."""
    oembed_url = f"https://vimeo.com/api/oembed.json?url={url}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(oembed_url)
            resp.raise_for_status()
            data = resp.json()

        title = data.get("title", "Untitled Video")
        author = data.get("author_name", "Unknown")
        text = f"Video: {title}\nBy: {author}\nURL: {url}"

        return ContentResult(
            title=title, text=text,
            html=f'<h2>{_esc_html(title)}</h2><p>By {_esc_html(author)}</p>',
            word_count=len(text.split()), source_domain=domain,
        )
    except Exception:
        return ContentResult(
            title="Video", text=f"Video URL: {url}",
            html=f'<p><a href="{url}">{url}</a></p>',
            word_count=3, source_domain=domain,
        )


# ── Article extraction ───────────────────────────────────────

async def _extract_article(url: str, domain: str) -> ContentResult:
    """Extract article content using readability."""
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=FETCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        if "application/pdf" in content_type:
            return ContentResult(
                title=url.split("/")[-1],
                text="[PDF content - extraction not yet supported]",
                html=f'<p>PDF: <a href="{url}">{url}</a></p>',
                word_count=0, source_domain=domain,
            )
        html = response.text

    doc = Document(html)
    title = doc.title()
    content_html = doc.summary()

    soup = BeautifulSoup(content_html, "lxml")
    # Remove all junk elements
    for tag in soup.find_all(["script", "style", "iframe", "noscript",
                              "audio", "video", "source", "button",
                              "nav", "footer", "aside", "form"]):
        tag.decompose()
    # Remove elements by class/id patterns (ads, captions, navigation)
    for tag in soup.find_all(True):
        classes = " ".join(tag.get("class", []))
        tag_id = tag.get("id", "")
        combined = f"{classes} {tag_id}".lower()
        if any(junk in combined for junk in [
            "caption", "toggle", "share", "social", "comment", "related",
            "newsletter", "subscribe", "promo", "ad-", "sidebar",
            "cookie", "popup", "modal", "audio-player",
        ]):
            tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    # Clean up common junk patterns in text
    import re
    text = re.sub(r"Your browser does not support the\s*audio\s*element\.?", "", text)
    text = re.sub(r"hide caption\s*toggle\s*caption", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    word_count = len(text.split())
    clean_html = str(soup)

    return ContentResult(
        title=title, text=text, html=clean_html,
        word_count=word_count, source_domain=domain,
    )


# ── Helpers ──────────────────────────────────────────────────

def _esc_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _text_to_html_paragraphs(text: str) -> str:
    paragraphs = text.split("\n\n") if "\n\n" in text else [text[i:i+500] for i in range(0, len(text), 500)]
    return "\n".join(f"<p>{_esc_html(p.strip())}</p>" for p in paragraphs if p.strip())
