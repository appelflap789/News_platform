"""What the library has on a foresight, found the way a topic finds its items (search/topics.members), and the
numbered blocks of items that are given to Claude.

A foresight made from a topic has exactly that topic's items, also as the topic changes. Any other foresight is
matched like a topic of its own: its name and statement by meaning, and by words its name and the names in it
(`first_terms`). Claude's own search terms are not added: on the owner's library twelve of them for "Demographic
ageing" pulled the point it is matched by away from the subject, and it went from 18 items to 10 (31 October 2026).
"""

from __future__ import annotations

import json
import re

from ... import db
from ...search import embed, meaning, query
from ...search import topics as topic_search

READ_BEST = 30  # the first reading: the best matches ...
READ_NEWEST = 10  # ... and the newest items besides, since the reading is about where things stand now
NEAR_ITEMS = 20  # what is read when one consequence is worked out further
NEAR_OWN = 6  # ... of which at least this many of the foresight's own items, when it has them
# How close an item must be to a consequence to be read when that consequence is worked out further. Measured
# with the multilingual MiniLM model on a copy of the owner's library (1,264 items, 31 October 2026), for four of
# Claude's consequences: the items stayed on the subject down to about 0.40 (diesel prices, strikes on Iran,
# migration politics); below it came military trains for migration, and AI in general for care robots.
NEAR_FLOOR = 0.40
EXCERPT_CHARS = 900  # of each item: its summary, and the opening of its text when the summary is short
# A trend is broad by nature; a signal or an event is about something more particular.
REACH = {"trend": "broad", "signal": "balanced", "event": "balanced"}


NAMES = re.compile(r"\b[A-Z][\w'’-]*(?:\s+(?:(?:of|the|for|de|van|von|der|al)\s+)?[A-Z][\w'’-]*)*")
LEADING = {"the", "a", "an"}
FIRST_TERMS = 6
# A name in more of the library than this says nothing about what an item is about. Counted on a copy of the owner's
# library (1,291 items, 31 October 2026): Hormuz 11%, Japan 11%, Qatar 5%, "Demographic" 3.5% pick out a subject;
# NATO 19%, Iran 26%, China 34%, Russian 35%, Ukraine 42%, US 49%, Europe 55% swamp it ("Europe swaps Russian gas
# for US LNG" found 167 items with them). Only judged once the library is large enough for shares to mean something.
COMMON_SHARE = 0.15
COMMON_FROM = 200


def first_terms(name: str, statement: str = "") -> list[str]:
    """The words a new foresight is first found by: its name, and the names in it and in its statement ("Strait of
    Hormuz" in "The Strait of Hormuz stays closed"), except names too common in the library to say anything. A whole
    sentence matches no item by its words, and without word matches to pull it towards the library's own material,
    matching by meaning finds too little (9 items on the strait instead of 44)."""
    found = [name.strip()]
    for text in (name, statement):
        for phrase in NAMES.findall(text or ""):
            words = phrase.split()
            while words and words[0].lower() in LEADING:
                words = words[1:]
            if words:
                found.append(" ".join(words))
    unique: dict[str, str] = {}
    for term in found:
        unique.setdefault(term.lower(), term)
    terms = list(unique.values())
    total = db.scalar("SELECT COUNT(*) FROM articles") or 0
    if total >= COMMON_FROM:
        def common(term: str) -> bool:
            match = query.term_expression(term)
            return bool(match) and db.scalar("SELECT COUNT(*) FROM articles_fts WHERE articles_fts MATCH ?",
                                             (match,)) > total * COMMON_SHARE
        terms = terms[:1] + [term for term in terms[1:] if not common(term)]
    return terms[:FIRST_TERMS]


def definition(foresight: dict) -> dict:
    """The foresight as search/topics.members wants a topic."""
    if foresight.get("topic_id"):
        topic = db.row("SELECT * FROM topics WHERE id = ?", (foresight["topic_id"],))
        if topic:
            topic["required_any"] = json.loads(topic["required_any"])
            topic["terms"] = json.loads(topic["terms"])
            return topic  # with its id, so what the owner said belongs to the topic counts here too
    terms = foresight.get("terms") or first_terms(foresight["name"], foresight.get("statement") or "")
    return {"name": foresight["name"], "description": foresight.get("statement") or "", "required_any": [],
            "terms": terms, "by_meaning": True,
            "reach": REACH.get(foresight.get("kind") or "trend", "balanced")}


def literature(foresight: dict) -> topic_search.Members:
    return topic_search.members(definition(foresight))


def reading(found: topic_search.Members) -> list[int]:
    """The items the first reading is written from: the best matches and the newest besides."""
    best = found.ids[:READ_BEST]
    known = topic_search.facts(found.ids)
    newest = sorted((i for i in found.ids if i in known and i not in best),
                    key=lambda i: (known[i]["date"], i), reverse=True)[:READ_NEWEST]
    return best + newest


def near(text: str, found: topic_search.Members, limit: int = NEAR_ITEMS) -> list[int]:
    """The items closest to one consequence: from the whole library, with some of the foresight's own."""
    if not embed.ready():
        return found.ids[:limit]
    index = embed.index()
    vector = index.place(embed.encode_query(text))
    own = [i for i, _ in meaning.nearest(vector, NEAR_OWN, floor=index.bar(NEAR_FLOOR), among=set(found.ids))]
    rest = [i for i, _ in meaning.nearest(vector, limit, floor=index.bar(NEAR_FLOOR), exclude=set(own))]
    return (own + rest)[:limit]


def articles(ids: list[int]) -> dict[int, dict]:
    found = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for row in db.rows(
                f"SELECT a.id, a.title, a.url, a.content_type, a.summary, a.ai_summary, a.fetched_at, a.image_url,"
                f" SUBSTR(a.text, 1, {EXCERPT_CHARS + 1}) AS opening,"
                f" COALESCE(NULLIF(a.published_at, ''), a.fetched_at) AS date, s.name AS source_name,"
                f" s.icon_url AS source_icon FROM articles a JOIN sources s ON s.id = a.source_id"
                f" WHERE a.id IN ({marks})", chunk):
            found[row["id"]] = row
    return found


def source(article: dict, number: int | None = None) -> dict:
    """How an item is kept on a foresight: enough to show and open it, also when it has left the library."""
    kept = {"article_id": article["id"], "title": article["title"], "url": article["url"],
            "source_name": article["source_name"], "date": article["date"][:10]}
    return {"n": number, **kept} if number is not None else kept


def blocks(ids: list[int]) -> tuple[list[str], list[dict], str]:
    """The items as numbered blocks for a request, oldest first; the sources by number; and the newest
    fetched_at among them."""
    found = articles(ids)
    ordered = sorted((i for i in ids if i in found), key=lambda i: (found[i]["date"], i))
    texts, sources = [], []
    for number, article_id in enumerate(ordered, start=1):
        article = found[article_id]
        about = " ".join((article["ai_summary"] or article["summary"]).split())
        if len(about) < 200:  # no summary to speak of: the opening of the text as well
            about = f"{about} {' '.join(article['opening'].split())}".strip()
        if len(about) > EXCERPT_CHARS:
            about = about[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " […]"
        texts.append(f"[{number}] {article['title']}\n"
                     f"Source: {article['source_name']} · {article['date'][:10]} · {article['content_type']}\n"
                     f"{about}")
        sources.append(source(article, number))
    through = max((found[i]["fetched_at"] for i in ordered), default="")
    return texts, sources, through


def present(sources: list[dict]) -> list[dict]:
    """Kept sources with their item's picture and source icon as they are now ('' when the item is gone)."""
    found = articles([source["article_id"] for source in sources])
    return [{**source, "image_url": found.get(source["article_id"], {}).get("image_url", ""),
             "source_icon": found.get(source["article_id"], {}).get("source_icon", ""),
             "gone": source["article_id"] not in found} for source in sources]
