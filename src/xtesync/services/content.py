"""Content extraction service - fetches URLs and extracts readable content."""

from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from readability import Document

from xtesync.models import ContentResult

USER_AGENT = "XteSync/0.1 (Reading Assistant; +https://github.com/abujiletsgo/xte-hub)"
FETCH_TIMEOUT = 30.0
MIN_CONTENT_LENGTH = 200

# Domains that need special handling
VIDEO_DOMAINS = {"youtube.com", "www.youtube.com", "youtu.be", "vimeo.com"}
PODCAST_DOMAINS = {"podcasts.apple.com", "open.spotify.com", "overcast.fm"}


async def extract(url: str) -> ContentResult:
    """Fetch a URL and extract its readable content."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    base_domain = ".".join(domain.split(".")[-2:]) if "." in domain else domain

    # Video URLs: use oEmbed for metadata
    if base_domain in {"youtube.com", "youtu.be", "vimeo.com"}:
        return await _extract_video(url, domain)

    # Standard article extraction
    return await _extract_article(url, domain)


async def _extract_article(url: str, domain: str) -> ContentResult:
    """Extract article content using readability."""
    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=FETCH_TIMEOUT,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

        content_type = response.headers.get("content-type", "")

        # PDF detection
        if "application/pdf" in content_type:
            return ContentResult(
                title=url.split("/")[-1],
                text="[PDF content - full extraction not yet supported]",
                html=f'<p>PDF document: <a href="{url}">{url}</a></p>',
                word_count=0,
                source_domain=domain,
            )

        html = response.text

    # Use readability to extract main content
    doc = Document(html)
    title = doc.title()
    content_html = doc.summary()

    # Clean with BeautifulSoup
    soup = BeautifulSoup(content_html, "lxml")

    # Remove scripts, styles, and unwanted elements
    for tag in soup.find_all(["script", "style", "iframe", "noscript"]):
        tag.decompose()

    # Extract plain text
    text = soup.get_text(separator="\n", strip=True)
    word_count = len(text.split())

    # Clean HTML for EPUB
    clean_html = str(soup)

    # Check for paywalled/empty content
    if len(text) < MIN_CONTENT_LENGTH:
        return ContentResult(
            title=title,
            text=text,
            html=clean_html,
            word_count=word_count,
            source_domain=domain,
        )

    return ContentResult(
        title=title,
        text=text,
        html=clean_html,
        word_count=word_count,
        source_domain=domain,
    )


async def _extract_video(url: str, domain: str) -> ContentResult:
    """Extract video metadata via oEmbed."""
    oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
    if "vimeo" in domain:
        oembed_url = f"https://vimeo.com/api/oembed.json?url={url}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(oembed_url)
            resp.raise_for_status()
            data = resp.json()

        title = data.get("title", "Untitled Video")
        author = data.get("author_name", "Unknown")

        text = f"Video: {title}\nBy: {author}\nURL: {url}"
        html = f"""<div class="video-meta">
            <h2>{title}</h2>
            <p>By {author}</p>
            <p><a href="{url}">Watch original</a></p>
        </div>"""

        return ContentResult(
            title=title,
            text=text,
            html=html,
            word_count=len(text.split()),
            source_domain=domain,
        )
    except Exception:
        return ContentResult(
            title="Video",
            text=f"Video URL: {url}",
            html=f'<p><a href="{url}">{url}</a></p>',
            word_count=3,
            source_domain=domain,
        )
