"""Finding the passages that answer a question: by meaning and by words, merged by rank, a few per item.

Meaning finds a passage that says the same thing in other words or another language; words find a name, a
programme or a number that meaning blurs. The two lists are merged the way the search box merges its two
(reciprocal rank fusion), and then at most a few passages are taken from each item, so that one long report
cannot fill the whole answer.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ... import config, db
from ...search import embed, query
from ...search import topics as topic_search
from . import passages

MEANING_HITS = 200  # how many passages of each kind are merged
WORD_HITS = 200
RANK_DAMPING = 60
# A passage counts as found by meaning when it is at least this close to the question (centred similarity, the
# multilingual MiniLM model). Measured on a copy of the owner's library: see the README, section "Ask the library".
FLOOR = 0.35
BELOW_BEST = 0.25  # ... and not much further from it than the closest passage is
# Below this, the closest passage is probably not about the question at all: the questions the library answers
# scored 0.60 to 0.77 at best on the copy, "How do zebra crossings improve pedestrian safety?" 0.49.
WEAK = 0.55
PER_ITEM = 3  # passages from one item at most
SINCE = {"month": 31, "quarter": 92, "year": 366}
MAX_TERMS = 12
# Words a question is made of that say nothing about what it asks.
STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between both
but by can could did do does doing down during each few for from further had has have having he her here hers him
his how i if in into is it its itself just me more most my no nor not now of off on once only or other our ours out
over own same she should so some such than that the their them then there these they this those through to too
under until up very was we were what when where which while who whom why will with would you your yours tell know
think say said give make get much many way ways mean means does did done going happen happening happened latest
recent recently currently current now today library items item sources source article articles say says according
de het een en van in op te dat die is voor met zijn er aan niet ook als bij nog wat worden wordt hoe waarom welke
""".split())
WORD = re.compile(r"\w+", re.UNICODE)


@dataclass
class Found:
    """What was found for a question: the items, best first, each with its passages in reading order."""

    items: list[dict] = field(default_factory=list)
    passages: int = 0
    chars: int = 0
    library: int = 0  # how many items the question was asked of (the whole library, or the scope)
    best: float = 0.0  # how close the closest passage is in meaning (0 when meaning is not used)


def keywords(question: str) -> list[str]:
    """The words of a question that say what it is about, and its "quoted phrases"."""
    phrases = [p.strip() for p in re.findall(r'"([^"]+)"', question) if p.strip()]
    rest = re.sub(r'"[^"]+"', " ", question)
    words = [w for w in WORD.findall(rest) if len(w) >= 3 and w.lower() not in STOPWORDS and not w.isdigit()
             or (w.isdigit() and len(w) == 4)]  # a year is a good word
    unique: dict[str, str] = {}
    for term in phrases + words:
        unique.setdefault(term.lower(), term)
    return list(unique.values())[:MAX_TERMS]


def since_date(since: str) -> str:
    days = SINCE.get(since or "")
    if not days:
        return ""
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def allowed(*, topic_id: int | None = None, source_id: int | None = None, since: str = "") -> set[int] | None:
    """The items a question may be answered from, or None for the whole library."""
    where, params = [], []
    if source_id:
        where.append("a.source_id = ?")
        params.append(source_id)
    start = since_date(since)
    if start:
        where.append("COALESCE(NULLIF(a.published_at, ''), a.fetched_at) >= ?")
        params.append(start)
    chosen = None
    if where:
        chosen = {row["id"] for row in db.rows(f"SELECT a.id FROM articles a WHERE {' AND '.join(where)}", params)}
    if topic_id:
        topic = db.row("SELECT * FROM topics WHERE id = ?", (topic_id,))
        if topic:
            topic["required_any"] = json.loads(topic["required_any"])
            topic["terms"] = json.loads(topic["terms"])
            members = set(topic_search.members(topic).ids)
            chosen = members if chosen is None else chosen & members
    return chosen


def _by_meaning(question: str, among: set[int] | None) -> tuple[list[int], float]:
    found = passages.index()
    if not len(found):
        return [], 0.0
    np = embed.np
    vector = found.place(embed.encode_query(question))
    scores = found.matrix @ vector
    if among is not None:
        scores = np.where(np.isin(found.articles, np.fromiter(among, dtype=np.int64)), scores, -1.0)
    order = np.argsort(-scores)[:MEANING_HITS]
    if not len(order):
        return [], 0.0
    best = float(scores[order[0]])
    floor = max(found.bar(FLOOR), best - BELOW_BEST)
    # the closeness is given as it would be in a full library: a small one's thresholds are stricter (embed.bar)
    return [int(found.ids[i]) for i in order if scores[i] >= floor], best - found.bar(0)


def _by_words(question: str, among: set[int] | None) -> list[int]:
    match = query.any_of(keywords(question))
    if not match:
        return []
    hits = db.rows("SELECT f.rowid AS id, p.article_id FROM ask_fts f JOIN ask_passages p ON p.id = f.rowid"
                   " WHERE ask_fts MATCH ? ORDER BY bm25(ask_fts) LIMIT ?",
                   (match, WORD_HITS * (4 if among is not None else 1)))
    return [hit["id"] for hit in hits if among is None or hit["article_id"] in among][:WORD_HITS]


def find(question: str, *, topic_id: int | None = None, source_id: int | None = None, since: str = "",
         limit: int | None = None) -> Found:
    """The passages to answer a question from, grouped by item."""
    limit = limit or int(config.get("ask_passages"))
    among = allowed(topic_id=topic_id, source_id=source_id, since=since)
    library = len(among) if among is not None else db.scalar("SELECT COUNT(*) FROM articles") or 0
    if among is not None and not among:
        return Found(library=0)
    by_meaning, best = _by_meaning(question, among) if not embed.missing() else ([], 0.0)
    score: dict[int, float] = {}
    for hits in (by_meaning, _by_words(question, among)):
        for rank, passage_id in enumerate(hits):
            score[passage_id] = score.get(passage_id, 0.0) + 1 / (RANK_DAMPING + rank)
    if not score:
        return Found(library=library)
    ranked = sorted(score, key=lambda passage_id: -score[passage_id])
    rows: dict[int, dict] = {}
    for start in range(0, len(ranked), 500):
        chunk = ranked[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for row in db.rows(f"SELECT id, article_id, position, text FROM ask_passages WHERE id IN ({marks})", chunk):
            rows[row["id"]] = row
    picked: dict[int, list[dict]] = {}
    order: list[int] = []
    taken = 0
    seen: set[str] = set()  # a site often lists a report twice, both items with the text of the same PDF
    for passage_id in ranked:
        row = rows.get(passage_id)
        if row is None:
            continue
        said = " ".join(row["text"].lower().split())
        if said in seen:
            continue
        seen.add(said)
        mine = picked.setdefault(row["article_id"], [])
        if len(mine) >= PER_ITEM:
            continue
        if not mine:
            order.append(row["article_id"])
        mine.append(row)
        taken += 1
        if taken >= limit:
            break
    marks = ",".join("?" * len(order))
    articles = {row["id"]: row for row in db.rows(
        f"SELECT a.id, a.title, a.url, a.content_type, a.image_url, a.fetched_at,"
        f" COALESCE(NULLIF(a.published_at, ''), a.fetched_at) AS date, s.name AS source_name, s.icon_url AS source_icon"
        f" FROM articles a JOIN sources s ON s.id = a.source_id WHERE a.id IN ({marks})", order)}
    found = Found(library=library, best=round(best, 3))
    for article_id in order:
        article = articles.get(article_id)
        if article is None:  # removed since its passages were made; the next run sweeps them up
            continue
        chosen = sorted(picked[article_id], key=lambda row: row["position"])
        found.items.append({**article, "passages": [{"id": row["id"], "position": row["position"],
                                                     "text": row["text"]} for row in chosen]})
        found.passages += len(chosen)
        found.chars += sum(len(row["text"]) for row in chosen) + len(article["title"]) + 60
    return found
