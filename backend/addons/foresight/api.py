"""The foresight add-on's routes. Claude's steps start jobs, like every other Claude step; the rest is free."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ... import db
from ...ai import client as ai
from ...jobs import ACTIVE, manager
from ...search import embed, meaning
from ...search import topics as topic_search
from . import library, store, think, watch

router = APIRouter(prefix="/api")
KINDS = "^(trend|signal|event)$"
HORIZONS = "^(months|years|decades)$"
OUTCOMES = "^(|happened|did_not|too_early)$"
CARD_PICTURES = 6

# foresight id -> the job Claude is doing on it, so that its page shows the job also after a reload
_working: dict[int, str] = {}


class ForesightBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    statement: str = Field("", max_length=600)
    kind: str = Field("trend", pattern=KINDS)
    horizon: str = Field("years", pattern=HORIZONS)
    note: str = Field("", max_length=4000)
    topic_id: int | None = None


class ForesightPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    statement: str | None = Field(None, max_length=600)
    kind: str | None = Field(None, pattern=KINDS)
    horizon: str | None = Field(None, pattern=HORIZONS)
    note: str | None = Field(None, max_length=4000)
    topic_id: int | None = None  # only applied when it is sent; null = the whole library


class NodeBody(BaseModel):
    parent_id: int | None = None
    text: str = Field(min_length=1, max_length=400)
    mechanism: str = Field("", max_length=600)
    domain: str = Field("", pattern=f"^(|{'|'.join(think.DOMAINS)})$")
    likelihood: str = Field("", pattern=f"^(|{'|'.join(think.LIKELIHOODS)})$")
    horizon: str = Field("", pattern="^(|months|years|decades)$")


class NodePatch(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=400)
    mechanism: str | None = Field(None, max_length=600)
    note: str | None = Field(None, max_length=4000)
    outcome: str | None = Field(None, pattern=OUTCOMES)
    likelihood: str | None = Field(None, pattern=f"^({'|'.join(think.LIKELIHOODS)})$")


def _load(foresight_id: int) -> dict:
    foresight = store.foresight(foresight_id)
    if foresight is None:
        raise HTTPException(404, "Foresight not found.")
    return foresight


def _node(node_id: int) -> dict:
    found = store.node(node_id)
    if found is None:
        raise HTTPException(404, "Consequence not found.")
    return found


def _topic_exists(topic_id: int | None) -> None:
    if topic_id and db.scalar("SELECT 1 FROM topics WHERE id = ?", (topic_id,)) is None:
        raise HTTPException(404, "Topic not found.")


def _need_key() -> None:
    if not ai.available():
        raise HTTPException(400, "This needs an Anthropic API key. Add one on the Settings page.")


def _job_of(foresight_id: int) -> str | None:
    job_id = _working.get(foresight_id)
    job = manager.get(job_id) if job_id else None
    return job_id if job and job["status"] in ACTIVE else None


def _start(foresight_id: int, title: str, work) -> dict:
    if _job_of(foresight_id):
        raise HTTPException(409, "Claude is already working on this foresight. Wait until it has finished.")
    job = manager.submit("foresight", title, work)
    _working[foresight_id] = job.id
    return {"job_id": job.id}


def _price(plan: dict) -> dict:
    return {key: plan[key] for key in ("usd", "model_label", "reading", "matches", "waiting", "consequences", "ring")
            if key in plan}


def _pictures(foresight: dict, limit: int = CARD_PICTURES) -> list[str]:
    """For its card: pictures of the items it was read from, those that bear on it first, one per source first."""
    order = {"supports": 0, "nuances": 0, "contradicts": 1, "context": 2, "": 3}
    sources = sorted(foresight["reading_sources"], key=lambda s: order.get(s.get("stance", ""), 3))
    found = library.articles([s["article_id"] for s in sources])
    picked, used = [], set()
    for one_per_source in (True, False):
        for source in sources:
            article = found.get(source["article_id"])
            if not article or not article["image_url"] or article["image_url"] in picked:
                continue
            if one_per_source and article["source_name"] in used:
                continue
            picked.append(article["image_url"])
            used.add(article["source_name"])
            if len(picked) == limit:
                return picked
    return picked


def _seen(signposts: list[dict], visited: str) -> dict:
    hits = [hit for s in signposts for hit in s["seen"] if not hit.get("earlier")]
    return {"seen": len({hit["id"] for hit in hits}), "fresh": len({hit["id"] for hit in hits if hit["at"] > visited})}


def _card(foresight: dict) -> dict:
    nodes = store.nodes(foresight["id"])
    signposts = store.signposts(foresight["id"])
    topic = db.row("SELECT id, name FROM topics WHERE id = ?", (foresight["topic_id"],)) if foresight["topic_id"] else None
    return {
        "id": foresight["id"], "name": foresight["name"], "kind": foresight["kind"], "horizon": foresight["horizon"],
        "statement": foresight["statement"], "restated": foresight["restated"], "standing": foresight["standing"],
        "topic": topic, "consequences": len(nodes), "rings": max((n["ring"] for n in nodes), default=0),
        "signposts": len(signposts), **_seen(signposts, foresight["visited_at"]),
        "read": len(foresight["reading_sources"]), "cover": _pictures(foresight),
        "shape": [{"id": n["id"], "parent_id": n["parent_id"], "ring": n["ring"], "domain": n["domain"],
                   "basis": n["basis"]} for n in nodes],
        "created_at": foresight["created_at"], "updated_at": foresight["updated_at"],
        "read_at": foresight["read_at"], "job_id": _job_of(foresight["id"]),
    }


@router.get("/foresights")
def list_foresights() -> list[dict]:
    """Every foresight, as a card: the one updated last first."""
    cards = [_card(foresight) for foresight in store.foresights()]
    return sorted(cards, key=lambda card: (card["fresh"], card["updated_at"]), reverse=True)


@router.post("/foresights/preview")
def preview(body: ForesightBody) -> dict:
    """What the library has on a foresight before it is made, and what reading it would cost. Free."""
    _topic_exists(body.topic_id)
    draft = {**body.model_dump(), "id": None, "terms": []}
    found = library.literature(draft)
    plan = think.plan_reading(draft, found)
    sample = meaning.cards(found.ids[:5])
    return {
        **_price(plan), "sources": topic_search.breakdown(found)["sources"][:8],
        "sample": [{"id": i, "title": sample[i]["title"], "source_name": sample[i]["source_name"],
                    "date": (sample[i]["published_at"] or sample[i]["fetched_at"])[:10]} for i in found.ids[:5]
                   if i in sample],
        "meaning": embed.ready(), "ai": ai.available(),
    }


@router.post("/foresights")
def create(body: ForesightBody) -> dict:
    """Make a foresight and, when Claude is connected, have it read against the library straight away."""
    _topic_exists(body.topic_id)
    foresight_id = store.create({
        "name": body.name.strip(), "statement": body.statement.strip(), "kind": body.kind, "horizon": body.horizon,
        "note": body.note.strip(), "topic_id": body.topic_id,
        "terms": library.first_terms(body.name, body.statement),
    })
    started = None
    if ai.available():
        started = _start(foresight_id, f"Foresight: {body.name.strip()[:70]}",
                         lambda job: think.read(foresight_id, job))["job_id"]
    return {"id": foresight_id, "job_id": started}


@router.get("/foresights/{foresight_id}")
def get_foresight(foresight_id: int) -> dict:
    """Everything a foresight's page shows."""
    foresight = _load(foresight_id)
    watch.check_foresight(foresight_id)  # free: anything that reached the library since
    found = library.literature(foresight)
    nodes = store.nodes(foresight_id)
    signposts = store.signposts(foresight_id)
    hit_ids = sorted({hit["id"] for s in signposts for hit in s["seen"]})
    hits = library.articles(hit_ids)
    visited = foresight["visited_at"]
    for node in nodes:
        node["sources"] = library.present(node["sources"])
        node["signposts"] = []
        for signpost in (s for s in signposts if s["node_id"] == node["id"]):
            node["signposts"].append({
                "id": signpost["id"], "text": signpost["text"], "direction": signpost["direction"],
                "terms": signpost["terms"], "created_at": signpost["created_at"],
                "seen": [{**library.source(hits[hit["id"]]), "earlier": hit["earlier"],
                          "fresh": not hit["earlier"] and hit["at"] > visited}
                         for hit in reversed(signpost["seen"]) if hit["id"] in hits],
            })
        counted = {(s["direction"], h["article_id"]) for s in node["signposts"] for h in s["seen"] if not h["earlier"]}
        node["signs"] = {"for": sum(1 for d, _ in counted if d == "for"),
                         "against": sum(1 for d, _ in counted if d == "against")}
    ids = {node["id"] for node in nodes}
    checks = store.checks(foresight_id)
    for check in checks:
        check["sources"] = library.present(check["sources"])
    topic = db.row("SELECT id, name FROM topics WHERE id = ?", (foresight["topic_id"],)) if foresight["topic_id"] else None
    return {
        **foresight,
        "topic": topic,
        "reading_sources": library.present(foresight["reading_sources"]),
        "nodes": nodes,
        "links": [link for link in foresight["links"] if link["from"] in ids and link["to"] in ids],
        "checks": checks,
        **_seen(signposts, visited),
        "signposts": len(signposts),
        "literature": {"matches": len(found.ids), "mentions": len(found.mentions),
                       "trend": topic_search.trend(found), **topic_search.breakdown(found)},
        "next": {
            "reading": _price(think.plan_reading(foresight, found)),
            "recheck": _price(think.plan_recheck(foresight, found)) if foresight["read_at"] else None,
            "links": _price(think.plan_links(foresight)),
        },
        "max_ring": think.MAX_RING,
        "job_id": _job_of(foresight_id),
        "ai": ai.available(),
        "meaning": embed.ready(),
    }


@router.patch("/foresights/{foresight_id}")
def update(foresight_id: int, patch: ForesightPatch) -> dict:
    """Change what a foresight is about. What Claude read stays until it is read again."""
    foresight = _load(foresight_id)
    fields = {key: value.strip() if isinstance(value, str) else value
              for key, value in patch.model_dump(exclude_unset=True).items()}
    if "topic_id" in fields:
        _topic_exists(fields["topic_id"])
    if ("name" in fields or "statement" in fields) and not foresight["topic_id"]:  # found by its new names too
        named = library.first_terms(fields.get("name", foresight["name"]), fields.get("statement", foresight["statement"]))
        fields["terms"] = list(dict.fromkeys([*named, *foresight["terms"]]))
    store.update(foresight_id, **fields)
    return get_foresight(foresight_id)


@router.delete("/foresights/{foresight_id}")
def delete(foresight_id: int) -> dict:
    _load(foresight_id)
    if _job_of(foresight_id):
        raise HTTPException(409, "Claude is working on this foresight. Wait until it has finished.")
    store.remove(foresight_id)
    return {"deleted": True}


@router.post("/foresights/{foresight_id}/visit")
def visit(foresight_id: int) -> dict:
    """The page was opened: from now on, a signpost's match is new when it is newer than this."""
    _load(foresight_id)
    db.execute("UPDATE foresights SET visited_at = ? WHERE id = ?", (db.now(), foresight_id))
    return {"visited": True}


@router.post("/foresights/{foresight_id}/read")
def read(foresight_id: int) -> dict:
    """Read the foresight against the library and work out its first ring; when it was read before, start over."""
    foresight = _load(foresight_id)
    _need_key()
    again = bool(foresight["read_at"] or store.nodes(foresight_id))
    return _start(foresight_id, f"Foresight: {foresight['name'][:70]}",
                  lambda job: think.read(foresight_id, job, again=again))


@router.post("/foresights/{foresight_id}/recheck")
def recheck(foresight_id: int) -> dict:
    """Read the items that arrived since the last reading: what do they change?"""
    foresight = _load(foresight_id)
    _need_key()
    return _start(foresight_id, f"Re-check: {foresight['name'][:70]}", lambda job: think.recheck(foresight_id, job))


@router.post("/foresights/{foresight_id}/links")
def links(foresight_id: int) -> dict:
    """Find where consequences on different chains reinforce or dampen each other."""
    foresight = _load(foresight_id)
    _need_key()
    return _start(foresight_id, f"Links: {foresight['name'][:70]}", lambda job: think.find_links(foresight_id, job))


@router.get("/foresights/{foresight_id}/articles")
def articles(
    foresight_id: int,
    stance: str = Query("", pattern="^(|supports|nuances|contradicts|context)$"),
    sort: str = Query("relevance", pattern="^(newest|relevance)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    """The items about the foresight, or (with `stance`) those it was read from that took that stance."""
    foresight = _load(foresight_id)
    if not stance:
        return topic_search.search(library.literature(foresight), sort=sort, limit=limit, offset=offset)
    ids = [s["article_id"] for s in foresight["reading_sources"] if s.get("stance") == stance]
    rows = meaning.cards(ids)
    present = [i for i in ids if i in rows]
    if sort == "newest":
        present.sort(key=lambda i: (rows[i]["published_at"] or rows[i]["fetched_at"], i), reverse=True)
    return {"total": len(present), "items": [rows[i] for i in present[offset:offset + limit]]}


@router.post("/foresights/{foresight_id}/nodes")
def add_own(foresight_id: int, body: NodeBody) -> dict:
    """A consequence of the owner's own, on the first ring or after another one."""
    _load(foresight_id)
    ring = 1
    if body.parent_id is not None:
        parent = _node(body.parent_id)
        if parent["foresight_id"] != foresight_id:
            raise HTTPException(400, "That consequence belongs to another foresight.")
        if parent["ring"] >= think.MAX_RING:
            raise HTTPException(400, f"A foresight goes {think.MAX_RING} rings deep.")
        ring = parent["ring"] + 1
    node_id = store.add_node(foresight_id, body.parent_id, ring, {
        "text": " ".join(body.text.split()), "mechanism": " ".join(body.mechanism.split()),
        "domain": body.domain, "likelihood": body.likelihood, "horizon": body.horizon, "basis": "yours",
    })
    store.update(foresight_id)
    return {"id": node_id}


@router.get("/foresight-nodes/{node_id}/plan")
def expand_plan(node_id: int) -> dict:
    """What working out what follows from this consequence would read and cost. Free."""
    found = _node(node_id)
    if found["ring"] >= think.MAX_RING:
        return {"possible": False, "max_ring": think.MAX_RING}
    return {"possible": True, **_price(think.plan_expand(found))}


@router.post("/foresight-nodes/{node_id}/expand")
def expand(node_id: int) -> dict:
    found = _node(node_id)
    _need_key()
    if found["ring"] >= think.MAX_RING:
        raise HTTPException(400, f"A foresight goes {think.MAX_RING} rings deep: beyond that nearly everything is "
                                 f"guesswork.")
    return _start(found["foresight_id"], f"What follows: {found['text'][:70]}", lambda job: think.expand(node_id, job))


@router.patch("/foresight-nodes/{node_id}")
def update_node(node_id: int, patch: NodePatch) -> dict:
    """The owner's note, their look back (did it happen?), or their own wording or likelihood."""
    found = _node(node_id)
    fields = {key: value.strip() for key, value in patch.model_dump(exclude_unset=True).items() if value is not None}
    store.update_node(node_id, **fields)
    store.update(found["foresight_id"])
    return {"updated": True}


@router.delete("/foresight-nodes/{node_id}")
def delete_node(node_id: int) -> dict:
    """A consequence and everything that was worked out from it."""
    found = _node(node_id)
    if _job_of(found["foresight_id"]):
        raise HTTPException(409, "Claude is working on this foresight. Wait until it has finished.")
    store.remove_node(node_id)
    store.update(found["foresight_id"])
    return {"deleted": True}
