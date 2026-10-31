"""Topics: pages that collect what belongs to a subject, by its words and by its meaning, with a timeline,
a trend, and two texts written by Claude ("What is new" and "The long run")."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .. import db
from ..ai import briefing as writing
from ..ai import client as ai
from ..jobs import manager
from ..search import embed
from ..search import topics as topic_search
from ..search.expand import expand_topic

router = APIRouter(prefix="/api")
REACHES = "^(narrow|balanced|broad)$"
PICTURE = r"^(https?://\S+)?$"
CARD_PICTURES = 8  # offered to a topic's card, which shows the first four that load


class TopicBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    required_any: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    by_meaning: bool = True
    reach: str = Field("balanced", pattern=REACHES)
    auto_update: bool = False
    cover_url: str = Field("", max_length=2000, pattern=PICTURE)  # the picture pinned for its card; '' = automatic


class TopicPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    required_any: list[str] | None = None
    terms: list[str] | None = None
    by_meaning: bool | None = None
    reach: str | None = Field(None, pattern=REACHES)
    auto_update: bool | None = None
    cover_url: str | None = Field(None, max_length=2000, pattern=PICTURE)


class ExpandRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class Verdict(BaseModel):
    article_id: int
    verdict: str = Field(pattern="^(in|out|none)$")  # belongs here, not this, or take back what was said


def _tidy(terms: list[str]) -> list[str]:
    cleaned = [" ".join(t.split()) for t in terms]
    return list(dict.fromkeys(t for t in cleaned if t))


def _load(topic_id: int) -> dict:
    topic = db.row("SELECT * FROM topics WHERE id = ?", (topic_id,))
    if topic is None:
        raise HTTPException(404, "Topic not found.")
    for key in ("required_any", "terms", "briefing_sources"):
        topic[key] = json.loads(topic[key])
    for key in ("by_meaning", "auto_update"):
        topic[key] = bool(topic[key])
    return topic


def _all() -> list[dict]:
    return [_load(stored["id"]) for stored in db.rows("SELECT id FROM topics ORDER BY name COLLATE NOCASE")]


def _opening(text: str, limit: int = 220) -> str:
    """The first lines of a text Claude wrote, as plain words: no headline or headings, no pictures, no source
    numbers, no asterisks."""
    lines = [re.sub(r"^\s*(?:[-•*]|\d+\.)\s+", "", line)  # a list item reads on as a sentence
             for line in writing.without_pictures(text or "").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    plain = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", " ".join(lines))
    plain = re.sub(r"\s+", " ", re.sub(r"[*_`]+", "", plain)).strip()
    return plain if len(plain) <= limit else plain[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


@router.get("/topics")
def list_topics() -> list[dict]:
    """The topics, for the sidebar and for their cards on Home. A card shows a few pictures from the topic's
    newest items (or the one picture pinned for it), how recent the newest is, whether the topic is spiking,
    and the opening of the last "What is new"."""
    topics = []
    for topic in _all():
        found = topic_search.members(topic)
        news = writing.notes(topic["id"], 1)
        topics.append({
            "id": topic["id"], "name": topic["name"], "description": topic["description"],
            "matches": len(found.ids), "new": len(topic_search.new_since(found, topic["visited_at"])),
            "has_briefing": bool(topic["briefing"]),
            "cover": [topic["cover_url"]] if topic["cover_url"] else topic_search.pictures(found, CARD_PICTURES),
            "pinned": bool(topic["cover_url"]),
            "latest": topic_search.latest(found),
            "trend": topic_search.trend(found)["short"]["label"],
            "news": _opening(news[0]["text"]) if news else "",
        })
    return topics


@router.post("/topics/expand")
def expand(request: ExpandRequest) -> dict:
    """Ask Claude for search terms for a topic name. Nothing is saved."""
    usage = ai.Usage()
    result = expand_topic(request.name.strip(), usage)
    return {**result, "usage": usage.as_dict()}


@router.post("/topics/preview")
def preview(body: TopicBody) -> dict:
    """How many items a topic would collect, before saving it."""
    found = topic_search.members({
        "name": body.name.strip(), "description": body.description.strip(), "required_any": _tidy(body.required_any),
        "terms": _tidy(body.terms), "by_meaning": body.by_meaning, "reach": body.reach,
    })
    return {"matches": len(found.ids), "by_meaning": found.count("meaning"), "mentions": len(found.mentions)}


@router.post("/topics")
def create_topic(body: TopicBody) -> dict:
    required, terms = _tidy(body.required_any), _tidy(body.terms)
    if not required and not terms:
        terms = [body.name.strip()]
    cursor = db.execute(
        "INSERT INTO topics(name, description, required_any, terms, by_meaning, reach, auto_update, created_at,"
        " visited_at, cover_url) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (body.name.strip(), body.description.strip(), json.dumps(required), json.dumps(terms), int(body.by_meaning),
         body.reach, int(body.auto_update), db.now(), db.now(), body.cover_url),
    )
    return get_topic(cursor.lastrowid)


@router.get("/topics/{topic_id}")
def get_topic(topic_id: int) -> dict:
    """Everything a topic's page shows, except the timeline and the item wall, which are read in pages."""
    topic = _load(topic_id)
    found = topic_search.members(topic)
    topic["matches"] = len(found.ids)
    topic["mentions"] = len(found.mentions)
    topic["by"] = {why: found.count(why) for why in ("words", "meaning", "you")}
    topic.update(topic_search.breakdown(found))
    topic["new"] = len(topic_search.new_since(found, topic["visited_at"]))
    topic["trend"] = topic_search.trend(found)
    topic["pictures"] = topic_search.pictures(found, 12)  # to choose the card's picture from, in the editor
    topic["meaning"] = {"ready": embed.ready(), "reason": embed.missing()}

    # the two texts as news articles: headline, opening line, pictures, body (ai/briefing.article)
    earlier = writing.notes(topic_id)
    for note in earlier:
        note["sources"] = writing.with_pictures(note["sources"])
        note["article"] = writing.article(note["text"], note["sources"])
    topic["news"] = earlier[0] if earlier else None
    topic["earlier"] = earlier[1:]
    topic["briefing_sources"] = writing.with_pictures(topic["briefing_sources"])
    topic["briefing_article"] = (writing.article(topic["briefing"], topic["briefing_sources"])
                                 if topic["briefing"] else None)
    news = writing.plan_news(topic, found)
    topic["news_next"] = {"waiting": news["waiting"], "reading": news["reading"], "usd": round(news["usd"], 4),
                          "model_label": news["model_label"]}
    again = writing.plan_news(topic, found, rewrite=True) if topic["news"] else None  # the Rewrite button
    topic["news_rewrite"] = ({"reading": again["reading"], "usd": round(again["usd"], 4),
                              "model_label": again["model_label"]} if again and again["reading"] else None)
    long_run = writing.plan_long_run(topic, found)
    topic["long_run_next"] = {"reading": long_run["reading"], "usd": round(long_run["usd"], 4),
                              "model_label": long_run["model_label"]}

    everyone = _all()
    others = [(other, topic_search.members(other)) for other in everyone if other["id"] != topic_id]
    topic["up_next"] = topic_search.related(found.vector, others)
    position = [other["id"] for other in everyone].index(topic_id)
    ring = [{"id": other["id"], "name": other["name"]} for other in everyone]
    topic["previous"] = ring[position - 1] if len(ring) > 1 else None
    topic["next"] = ring[(position + 1) % len(ring)] if len(ring) > 1 else None
    return topic


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: int, patch: TopicPatch) -> dict:
    topic = _load(topic_id)
    name = (patch.name or topic["name"]).strip()
    description = topic["description"] if patch.description is None else patch.description.strip()
    required = topic["required_any"] if patch.required_any is None else _tidy(patch.required_any)
    terms = topic["terms"] if patch.terms is None else _tidy(patch.terms)
    by_meaning = topic["by_meaning"] if patch.by_meaning is None else patch.by_meaning
    if not required and not terms:
        raise HTTPException(400, "A topic needs at least one term.")
    db.execute(
        "UPDATE topics SET name = ?, description = ?, required_any = ?, terms = ?, by_meaning = ?, reach = ?,"
        " auto_update = ?, cover_url = ? WHERE id = ?",
        (name, description, json.dumps(required), json.dumps(terms), int(by_meaning), patch.reach or topic["reach"],
         int(topic["auto_update"] if patch.auto_update is None else patch.auto_update),
         topic["cover_url"] if patch.cover_url is None else patch.cover_url, topic_id),
    )
    return get_topic(topic_id)


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int) -> dict:
    _load(topic_id)
    db.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    return {"deleted": True}


@router.post("/topics/{topic_id}/visit")
def visit(topic_id: int) -> dict:
    """The page was opened: from now on, "new" means newer than this."""
    _load(topic_id)
    db.execute("UPDATE topics SET visited_at = ? WHERE id = ?", (db.now(), topic_id))
    return {"visited": True}


@router.post("/topics/{topic_id}/items")
def say(topic_id: int, body: Verdict) -> dict:
    """Tell a topic that an item belongs to it, or does not. The topic also learns from it: what it collects
    by meaning moves towards the items that belong and away from the ones that do not."""
    _load(topic_id)
    if db.scalar("SELECT 1 FROM articles WHERE id = ?", (body.article_id,)) is None:
        raise HTTPException(404, "Article not found.")
    if body.verdict == "none":
        db.execute("DELETE FROM topic_items WHERE topic_id = ? AND article_id = ?", (topic_id, body.article_id))
    else:
        db.execute(
            "INSERT INTO topic_items(topic_id, article_id, verdict) VALUES(?,?,?)"
            " ON CONFLICT(topic_id, article_id) DO UPDATE SET verdict = excluded.verdict",
            (topic_id, body.article_id, body.verdict))
    return {"matches": len(topic_search.members(_load(topic_id)).ids)}


@router.get("/topics/{topic_id}/timeline")
def topic_timeline(topic_id: int, since: str = "", limit: int = Query(40, ge=1, le=100),
                   offset: int = Query(0, ge=0)) -> dict:
    """The topic's items by date; near-identical items are one entry. `since` marks what is new."""
    topic = _load(topic_id)
    return topic_search.timeline(topic_search.members(topic), since=since, limit=limit, offset=offset)


@router.get("/topics/{topic_id}/articles")
def topic_articles(
    topic_id: int,
    source_id: int | None = None,
    sort: str = Query("relevance", pattern="^(newest|relevance)$"),
    scope: str = Query("about", pattern="^(about|mentions|all)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """The items that are about the topic, the ones that only mention it, or both."""
    found = topic_search.members(_load(topic_id))
    return topic_search.search(found, scope=scope, source_id=source_id, sort=sort, limit=limit, offset=offset)


@router.get("/articles/{article_id}/topics")
def topics_of(article_id: int) -> list[dict]:
    """Every topic, with whether this item is in it and what you said about it. For the reader."""
    if db.scalar("SELECT 1 FROM articles WHERE id = ?", (article_id,)) is None:
        raise HTTPException(404, "Article not found.")
    listed = []
    for topic in _all():
        found = topic_search.members(topic)
        listed.append({"id": topic["id"], "name": topic["name"], "why": found.why.get(article_id),
                       "verdict": topic_search.verdicts(topic["id"]).get(article_id)})
    return listed


def _need_key(what: str) -> None:
    if not ai.available():
        raise HTTPException(400, f"{what} needs an Anthropic API key. Add one on the Settings page.")


@router.post("/topics/{topic_id}/news")
def news(topic_id: int, rewrite: bool = False) -> dict:
    """Write "What is new" from the items that arrived since the last update; with `rewrite`, write the latest
    update again from the items it was written from."""
    topic = _load(topic_id)
    _need_key("An update")
    job = manager.submit("news", f"What is new: {topic['name']}",
                         lambda job: writing.write_news(topic_id, job, rewrite=rewrite), topic_id=topic_id)
    return {"job_id": job.id}


@router.post("/topics/{topic_id}/briefing")
def briefing(topic_id: int) -> dict:
    """Write "The long run": the standing summary of the topic."""
    topic = _load(topic_id)
    _need_key("A summary")
    job = manager.submit("briefing", f"The long run: {topic['name']}",
                         lambda job: writing.write_briefing(topic_id, job), topic_id=topic_id)
    return {"job_id": job.id}
