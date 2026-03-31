"""API router for CrossPoint device communication — connect and sync EPUBs."""

import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from xtesync import database as db
from xtesync.services import sync



logger = logging.getLogger(__name__)
router = APIRouter(prefix="/device", tags=["device"])

UPLOAD_PATH = "/Books"
TIMEOUT = 10.0


class ConnectRequest(BaseModel):
    ip: str


# Session state — no device until user connects
_device_url: str | None = None


@router.get("/status")
async def device_status():
    """Return current connection state. Only pings device if already connected."""
    if not _device_url:
        return {"connected": False, "url": None}

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{_device_url}/api/status")
            resp.raise_for_status()
            data = resp.json()
            return {
                "connected": True,
                "url": _device_url,
                "version": data.get("version"),
                "ip": data.get("ip"),
                "freeHeap": data.get("freeHeap"),
                "rssi": data.get("rssi"),
            }
    except Exception:
        return {"connected": False, "url": _device_url}


@router.post("/connect")
async def connect_device(body: ConnectRequest):
    """Connect to a CrossPoint device by IP. Verifies it's reachable."""
    global _device_url
    url = f"http://{body.ip.strip()}"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{url}/api/status")
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Cannot reach device at {url}: {e}")

    _device_url = url
    return {
        "connected": True,
        "url": _device_url,
        "version": data.get("version"),
        "ip": data.get("ip"),
        "freeHeap": data.get("freeHeap"),
        "rssi": data.get("rssi"),
    }


@router.post("/disconnect")
async def disconnect_device():
    """Disconnect from the device."""
    global _device_url
    _device_url = None
    return {"connected": False}


@router.get("/files")
async def list_device_files(path: str = "/Books"):
    """List files on the device."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{_device_url}/api/files", params={"path": path})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Device unreachable: {e}")


@router.post("/sync/{sync_id}")
async def sync_to_device(sync_id: int):
    """Upload a pending briefing EPUB directly to the CrossPoint device."""
    async with db.get_db_ctx() as conn:
        # Get sync record
        cursor = await conn.execute("SELECT * FROM sync_state WHERE id = ?", (sync_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sync record not found")

        record = dict(row)
        epub_path = record.get("epub_path")
        if not epub_path or not Path(epub_path).exists():
            raise HTTPException(status_code=404, detail="EPUB file not found")

        # Upload to device
        file_path = Path(epub_path)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    resp = await client.post(
                        f"{_device_url}/upload",
                        params={"path": UPLOAD_PATH},
                        files={"file": (file_path.name, f, "application/epub+zip")},
                    )
                    resp.raise_for_status()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Upload timed out — device may be slow")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Upload failed: {e}")

        # Mark as synced
        await sync.mark_synced(conn, sync_id)

        return {
            "status": "synced",
            "file": file_path.name,
            "device": _device_url,
            "briefing_date": record["briefing_date"],
        }


@router.post("/sync-item/{item_id}")
async def sync_item_to_device(item_id: int):
    """Upload a single item's full EPUB to the device."""
    async with db.get_db_ctx() as conn:
        item = await db.get_item(conn, item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")

        epub_path = item.get("full_epub_path")
        if not epub_path or not Path(epub_path).exists():
            raise HTTPException(status_code=404, detail="EPUB not generated for this item")

        file_path = Path(epub_path)
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                with open(file_path, "rb") as f:
                    resp = await client.post(
                        f"{_device_url}/upload",
                        params={"path": UPLOAD_PATH},
                        files={"file": (file_path.name, f, "application/epub+zip")},
                    )
                    resp.raise_for_status()
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Upload failed: {e}")

        return {
            "status": "synced",
            "file": file_path.name,
            "title": item.get("title"),
            "device": _device_url,
        }
