"""Home's front page: the newest topic updates as its headlines, and what reached the library since you were last
here.

The headlines are the "What is new" texts Claude already wrote for the topics (`topic_notes`), the newest one per
topic, newest first; nothing is written for Home itself, so the front page costs nothing.

"Since you were last here" needs to know when that was. Opening Home records a visit (`POST /api/home/visit`);
a visit within half an hour of the one before is the same visit (going to an item and back, a refresh), so the
counts stay put while you read and start over when you come back later. The two times are kept in the settings
table under keys of their own, which are not settings: nothing shows or changes them.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from .. import db
from ..ai import briefing as writing
from ..search import topics as topic_search
from .topics import _opening  # the first lines of a text Claude wrote, as plain words, as on a topic card

router = APIRouter(prefix="/api")

STORIES = 5  # topic updates on the front page: one large, the rest as headlines beside it
SAME_VISIT = timedelta(minutes=30)
FIRST_LOOK = timedelta(days=1)  # before the first recorded visit, "since you were last here" is the last day
SEEN, BEFORE = "home_seen_at", "home_before_at"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _stamp(key: str) -> str:
    row = db.row("SELECT value FROM settings WHERE key = ?", (key,))
    return json.loads(row["value"]) if row else ""


def _keep(key: str, value: str) -> None:
    db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (key, json.dumps(value)))


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, TIME_FORMAT).replace(tzinfo=timezone.utc)


def last_visit() -> str:
    """When you were last on Home before this visit."""
    return _stamp(BEFORE) or (datetime.now(timezone.utc) - FIRST_LOOK).strftime(TIME_FORMAT)


@router.post("/home/visit")
def visit() -> dict:
    now = db.now()
    seen = _stamp(SEEN)
    if seen and _parse(now) - _parse(seen) > SAME_VISIT:
        _keep(BEFORE, seen)  # a new visit: what is new is counted from the end of the last one
    _keep(SEEN, now)
    return {"since": last_visit()}


def _stories() -> list[dict]:
    rows = db.rows(
        "SELECT n.*, t.name AS topic_name FROM topic_notes n JOIN topics t ON t.id = n.topic_id"
        " WHERE n.id IN (SELECT MAX(id) FROM topic_notes GROUP BY topic_id) ORDER BY n.created_at DESC, n.id DESC"
        " LIMIT ?", (STORIES,))
    stories = []
    for row in rows:
        sources = writing.with_pictures(json.loads(row["sources"]))
        text = writing.article(row["text"], sources)
        lead = next((source for source in sources if source["n"] == text["lead"]), None)
        stories.append({
            "topic_id": row["topic_id"], "topic_name": row["topic_name"], "written_at": row["created_at"],
            "headline": text["headline"] or f"What is new: {row['topic_name']}",
            "standfirst": text["standfirst"] or _opening(text["body"], 260),
            "image_url": lead["image_url"] if lead else "",
            "items": row["items"], "sources": len({source["source_name"] for source in sources}),
        })
    return stories


def _since(stamp: str) -> dict:
    rows = db.rows("SELECT a.id, a.source_id, s.name FROM articles a JOIN sources s ON s.id = a.source_id"
                   " WHERE a.fetched_at > ?", (stamp,))
    fresh = {row["id"] for row in rows}
    per_source: dict[str, int] = {}
    for row in rows:
        per_source[row["name"]] = per_source.get(row["name"], 0) + 1
    moved = []
    if fresh:
        for topic in db.rows("SELECT * FROM topics"):
            topic["required_any"] = json.loads(topic["required_any"])
            topic["terms"] = json.loads(topic["terms"])
            count = len(fresh & set(topic_search.members(topic).ids))
            if count:
                moved.append({"id": topic["id"], "name": topic["name"], "new": count})
    moved.sort(key=lambda topic: (-topic["new"], topic["name"].lower()))
    return {
        "at": stamp, "items": len(fresh),
        "sources": sorted(({"name": name, "new": n} for name, n in per_source.items()), key=lambda s: -s["new"]),
        "topics": moved,
    }


@router.get("/home")
def front_page() -> dict:
    """The front page's headlines and what is new since the last visit (`visit` is not recorded here)."""
    return {"stories": _stories(), "since": _since(last_visit())}
