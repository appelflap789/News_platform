"""The scrape log: every scrape and every saved link of the last days, with what it stored and what went wrong.
The dashboard groups the runs by day in the reader's own time zone, so the days are not cut here."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

from .. import db
from ..connectors import connectors
from ..schemas import Recipe

router = APIRouter(prefix="/api")

KINDS = ("scrape", "save")
ITEMS_PER_RUN = 60  # titles listed per run; a first scrape can store hundreds
PROBLEMS_PER_RUN = 25


@router.get("/scrape-log")
def scrape_log(days: int = Query(14, ge=1, le=90)) -> dict:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    jobs = db.rows(
        f"SELECT id, kind, title, source_id, status, logs, result, error, created_at, finished_at FROM jobs "
        f"WHERE kind IN ({','.join('?' * len(KINDS))}) AND created_at >= ? ORDER BY created_at DESC, rowid DESC",
        (*KINDS, since))
    sources = {s["id"]: s for s in db.rows("SELECT id, name, recipe FROM sources")}
    return {"days": days, "runs": [_run(job, sources) for job in jobs]}


def _run(job: dict, sources: dict[int, dict]) -> dict:
    result = json.loads(job["result"] or "null") or {}
    saved = result.get("article_id") if job["kind"] == "save" else None
    # a saved link's job has no source: it is the Saved articles/videos/podcasts its item went to
    source_id = job["source_id"] or (db.scalar("SELECT source_id FROM articles WHERE id = ?", (saved,)) if saved else None)
    source = sources.get(source_id)
    logs = json.loads(job["logs"] or "[]")
    feeds = result.get("feeds") or []
    labels = _connector_labels(source)
    new_ids = ([saved] if result.get("new") else []) if saved else _stored(job, result)
    return {
        "id": job["id"],
        "kind": job["kind"],
        "status": job["status"],
        "scheduled": job["title"].startswith("Scheduled update"),
        "source_id": source_id if source else None,
        # a source deleted since keeps the name its job was given
        "source": source["name"] if source else job["title"].split(": ", 1)[-1],
        "started_at": job["created_at"],
        "finished_at": job["finished_at"],
        "error": job["error"],
        "new": int(result.get("new") or 0),
        "failed": int(result.get("failed") or 0),
        "left_out": int(result.get("left_out") or 0),
        "partial": sum(int(feed.get("partial") or 0) for feed in feeds) + (1 if result.get("partial") is True else 0),
        "feeds": [
            {"feed": feed.get("feed", ""), "scraper": labels.get(feed.get("feed", ""), ""),
             "new": int(feed.get("new") or 0), "failed": int(feed.get("failed") or 0),
             "left_out": int(feed.get("left_out") or 0), "partial": int(feed.get("partial") or 0),
             "error": feed.get("error", "")}
            for feed in feeds
        ],
        "problems": [{"level": entry.get("level", "warn"), "msg": entry.get("msg", "")}
                     for entry in logs if entry.get("level") in ("warn", "error")][:PROBLEMS_PER_RUN],
        "items": _titles(new_ids),
        "more_items": max(0, len(new_ids) - ITEMS_PER_RUN),
    }


def _connector_labels(source: dict | None) -> dict[str, str]:
    """Feed name -> how that feed is read (RSS feed, sitemap, a built scraper…)."""
    if not source:
        return {}
    try:
        recipe = Recipe.model_validate_json(source["recipe"])
    except ValueError:
        return {}
    labels = {}
    for feed in recipe.feeds:
        try:
            labels[feed.name] = getattr(connectors.get(feed.connector), "label", feed.connector)
        except KeyError:
            labels[feed.name] = feed.connector
    return labels


def _stored(job: dict, result: dict) -> list[int]:
    """The items the run added: those of its source stored while it ran (the jobs table keeps no list)."""
    if not job["source_id"] or not result.get("new"):
        return []
    until = job["finished_at"] or db.now()
    return [r["id"] for r in db.rows(
        "SELECT id FROM articles WHERE source_id = ? AND fetched_at >= ? AND fetched_at <= ? ORDER BY id",
        (job["source_id"], job["created_at"], until))]


def _titles(ids: list[int]) -> list[dict]:
    shown = ids[:ITEMS_PER_RUN]
    if not shown:
        return []
    found = {r["id"]: r for r in db.rows(
        f"SELECT id, title, content_type FROM articles WHERE id IN ({','.join('?' * len(shown))})", shown)}
    return [{"id": i, "title": found[i]["title"], "content_type": found[i]["content_type"]} for i in shown if i in found]
