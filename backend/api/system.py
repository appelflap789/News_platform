"""Everything about the platform itself: what plugins exist, settings, the API key, jobs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import __version__, addons, config, db
from ..ai import client as ai
from ..analyzers import analyzers
from ..connectors import connectors
from ..extractors import extractors
from ..extractors.base import all_fields
from ..fetchers import fetchers
from ..jobs import manager
from ..pipeline import comments, videos
from ..pipeline.enrich import prices as label_prices
from ..pipeline.translate import prices
from ..schemas import CONTENT_TYPES
from ..search import embed

router = APIRouter(prefix="/api")


class SettingsBody(BaseModel):
    values: dict[str, object]


class ApiKeyBody(BaseModel):
    key: str


def _other_keys() -> dict:
    """Whether the two Google keys are set, with the last characters to tell them apart. Never the key."""
    status = {}
    for name in config.OTHER_KEYS:
        key = config.other_key(name)
        status[name] = {"set": bool(key), "key_hint": f"…{key[-4:]}" if len(key) > 8 else ""}
    return status


def _ai_status() -> dict:
    key = config.api_key()
    return {"available": ai.available(), "key_hint": f"…{key[-4:]}" if len(key) > 8 else ""}


@router.get("/meta")
def meta() -> dict:
    """What this installation can do. The dashboard builds its forms from this."""
    return {
        "version": __version__,
        "ai": _ai_status(),
        "translation": prices(),
        "labels": label_prices(),
        "meaning": embed.status(),
        "keys": _other_keys(),
        "videos": videos.prices(),
        "comments": comments.prices(),
        "addons": addons.meta(),  # the add-ons there are (backend/addons): the dashboard shows only these
        # For saying beforehand how long going back N items takes: the pause between two requests to one site,
        # and what a page takes to come. Measured at a pause of 1 second: 1.2 seconds an item on csis.org
        # (160 items), 2.5 on clingendael.org (14 items, with the listing pages that were walked to reach them).
        "scrape": {"seconds_per_item": round(float(config.get("request_delay_seconds")) + 1.0, 2),
                   "daily_time": config.get("daily_scrape_time")},  # when the sources set to Every day run
        "connectors": connectors.describe(),
        "extractors": extractors.describe(),
        "article_fields": [f.as_dict() for f in all_fields()],
        "analyzers": analyzers.describe(),
        "fetchers": fetchers.describe(),
        "content_types": CONTENT_TYPES,
    }


@router.get("/stats")
def stats() -> dict:
    return {
        "sources": db.scalar("SELECT COUNT(*) FROM sources"),
        "articles": db.scalar("SELECT COUNT(*) FROM articles"),
        "topics": db.scalar("SELECT COUNT(*) FROM topics"),
        "removed": db.scalar("SELECT COUNT(*) FROM removed"),  # items you took out yourself (backend/removed.py)
        "favorites": db.scalar("SELECT COUNT(*) FROM articles WHERE favorite_at != ''"),  # the items you starred
        # the single items saved by their address (pipeline/scrape.py, SAVED); the dashboard shows them together
        "saved": db.scalar("SELECT COUNT(*) FROM articles a JOIN sources s ON s.id = a.source_id"
                           " WHERE s.analyzer LIKE 'saved-%'"),
        "content_types": db.rows(
            "SELECT content_type, COUNT(*) AS n FROM articles GROUP BY content_type ORDER BY n DESC"),
    }


@router.get("/settings")
def get_settings() -> dict:
    return {"spec": config.SETTINGS, "values": config.all_values(), "ai": _ai_status()}


@router.put("/settings")
def put_settings(body: SettingsBody) -> dict:
    try:
        config.update(body.values)
    except (ValueError, TypeError) as error:
        raise HTTPException(400, str(error)) from error
    return get_settings()


@router.put("/settings/api-key")
def put_api_key(body: ApiKeyBody) -> dict:
    """Save the Anthropic API key to `.env`. The key is never sent back to the browser."""
    key = body.key.strip()
    if key and not key.startswith("sk-ant-"):
        raise HTTPException(400, "That does not look like an Anthropic API key (it should start with sk-ant-).")
    config.save_api_key(key)
    return _ai_status()


@router.put("/settings/keys/{name}")
def put_other_key(name: str, body: ApiKeyBody) -> dict:
    """Save the YouTube Data API key ('youtube') or the Gemini API key ('gemini') to `.env`."""
    if name not in config.OTHER_KEYS:
        raise HTTPException(404, "There is no key by that name.")
    key = body.key.strip()
    if key and (len(key) < 20 or " " in key):
        raise HTTPException(400, "That does not look like an API key from Google (they are about 39 characters, "
                                 "without spaces).")
    config.save_other_key(name, key)
    return _other_keys()


@router.post("/meaning/embed")
def embed_now() -> dict:
    """Embed the items that have no embedding yet. Free: the model runs on this computer."""
    job_id = start_embedding()
    if job_id is None:
        raise HTTPException(400, embed.missing() or "Every item already has an embedding.")
    return {"job_id": job_id}


def start_embedding() -> str | None:
    """Start the embedding job unless there is nothing to do, it cannot run, or one is running already."""
    if embed.missing() or not embed.pending():
        return None
    running = next((job for job in manager.recent(20) if job["kind"] == "embed"
                    and job["status"] in ("queued", "running")), None)
    if running:
        return running["id"]
    return manager.submit("embed", "Understanding what items are about", embed.refresh).id


@router.get("/jobs")
def list_jobs(limit: int = Query(40, ge=1, le=200)) -> list[dict]:
    return manager.recent(limit)


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    return {"cancelled": manager.cancel(job_id)}
