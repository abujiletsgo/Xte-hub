"""XteSync FastAPI application entry point."""

from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from xtesync.database import init_db
from xtesync.routers import briefings, channels, device, items

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="XteSync",
    description="Reading experience & navigation system for Xteink e-readers. "
    "Three-layer depth: Daily Briefing → In-Depth Summary → Raw Reading Files.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(items.router, prefix="/api")
app.include_router(briefings.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(device.router, prefix="/api")


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api")
async def api_info():
    return {
        "name": "XteSync",
        "version": "0.1.0",
        "description": "Reading experience & navigation for Xteink e-readers",
        "endpoints": {
            "submit_url": "POST /api/items/url",
            "list_items": "GET /api/items",
            "get_item": "GET /api/items/{id}",
            "generate_briefing": "POST /api/briefings/generate",
            "get_briefing": "GET /api/briefings/{date}",
            "latest_briefing": "GET /api/briefings/latest",
            "download_epub": "GET /api/briefings/{date}/download",
            "pending_syncs": "GET /api/briefings/sync/pending",
        },
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


def cli():
    """Entry point for the xtesync command."""
    uvicorn.run(
        "xtesync.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    cli()
