"""Finding items by what they are about: the search box, and "More like this" in the reader.

The search box uses both ways of finding at once. Words (FTS5, see query.py) are exact: a name, a programme, a
quoted phrase. Meaning (embed.py) finds what is about the same thing in other words or another language. The two
result lists are merged by rank, so an item both ways agree on comes first.
"""

from __future__ import annotations

from .. import db
from . import embed, query

WORD_HITS = 300  # how many results of each kind are merged
MEANING_HITS = 60
# An item counts as found by meaning when it is at least this close to the question, and not much further
# away than the closest item is. Measured with the multilingual MiniLM model on a library of 380 news items
# and papers (October 2026): unrelated pairs sit around 0, what a question is about scores 0.4 to 0.8, and
# the best match for a question the library has nothing on ("zebra crossing") scored 0.39.
FLOOR = 0.40
BELOW_BEST = 0.25
RANK_DAMPING = 60  # reciprocal rank fusion: score = sum of 1 / (60 + rank)
SIMILAR_FLOOR = 0.40


def nearest(vector, limit: int, *, floor: float = 0.0, among: set[int] | None = None,
            exclude: set[int] | None = None) -> list[tuple[int, float]]:
    """The items closest to a vector, closest first, as (article id, similarity)."""
    index = embed.index()
    if not len(index):
        return []
    scores = index.matrix @ vector
    order = embed.np.argsort(-scores)
    found = []
    for position in order:
        score = float(scores[position])
        if score < floor:
            break
        article_id = int(index.ids[position])
        if (among is not None and article_id not in among) or (exclude and article_id in exclude):
            continue
        found.append((article_id, score))
        if len(found) >= limit:
            break
    return found


def cards(ids: list[int]) -> dict[int, dict]:
    """The rows the cards are drawn from, by article id."""
    found: dict[int, dict] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for row in db.rows(f"SELECT {query.CARD_COLUMNS} FROM articles a JOIN sources s ON s.id = a.source_id"
                           f" WHERE a.id IN ({marks})", chunk):
            found[row["id"]] = row
    return found


def snippets(match: str, ids: list[int]) -> dict[int, str]:
    """The passage that matched, for the items that were found by their words."""
    if not match or not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {row["id"]: row["snippet"] for row in db.rows(
        f"SELECT rowid AS id, snippet(articles_fts, -1, '{query.MARK_OPEN}', '{query.MARK_CLOSE}', ' … ', 28)"
        f" AS snippet FROM articles_fts WHERE articles_fts MATCH ? AND rowid IN ({marks})", [match, *ids])}


def similar(article_id: int, limit: int = 6) -> list[dict]:
    """Items about the same thing as this one, closest first."""
    if not embed.ready():
        return []
    index = embed.index()
    if article_id not in index.row:
        return []
    close = nearest(index.matrix[index.row[article_id]], limit, floor=index.bar(SIMILAR_FLOOR),
                    exclude={article_id})
    found = cards([found_id for found_id, _ in close])
    return [{**found[found_id], "similarity": round(score, 3)} for found_id, score in close if found_id in found]


def search(text: str, *, source_id: int | None = None, content_type: str = "", sort: str = "relevance",
           limit: int = 30, offset: int = 0) -> dict:
    """The search box: items that contain the words, and items that are about the same thing."""
    match = query.text_match(text)
    if not embed.ready():
        return query.search(match, source_id=source_id, content_type=content_type, sort=sort, limit=limit,
                            offset=offset)
    where, params = [], []
    if source_id:
        where.append("a.source_id = ?")
        params.append(source_id)
    if content_type:
        where.append("a.content_type = ?")
        params.append(content_type)
    by_words: list[int] = []
    if match:
        condition = " AND ".join(["articles_fts MATCH ?", *where])
        by_words = [row["id"] for row in db.rows(
            f"SELECT a.id, bm25(articles_fts, {query.WEIGHTS}) AS score FROM articles_fts"
            f" JOIN articles a ON a.id = articles_fts.rowid WHERE {condition} ORDER BY score, a.id DESC LIMIT ?",
            [match, *params, WORD_HITS])]
    allowed = None
    if where:
        allowed = {row["id"] for row in db.rows(f"SELECT a.id FROM articles a WHERE {' AND '.join(where)}", params)}
    index = embed.index()
    vector = index.place(embed.encode_query(text))
    best = nearest(vector, 1, among=allowed)
    by_meaning = []
    if best:
        by_meaning = nearest(vector, MEANING_HITS, floor=max(index.bar(FLOOR), best[0][1] - BELOW_BEST),
                             among=allowed)

    score: dict[int, float] = {}
    for rank, article_id in enumerate(by_words):
        score[article_id] = score.get(article_id, 0.0) + 1 / (RANK_DAMPING + rank)
    for rank, (article_id, _) in enumerate(by_meaning):
        score[article_id] = score.get(article_id, 0.0) + 1 / (RANK_DAMPING + rank)
    found = cards(list(score))
    ordered = sorted(found, key=lambda article_id: (-score[article_id], -article_id))
    if sort == "newest":
        ordered.sort(key=lambda i: (found[i]["published_at"] or found[i]["fetched_at"], i), reverse=True)
    page = ordered[offset:offset + limit]
    words = set(by_words)
    passages = snippets(match, [article_id for article_id in page if article_id in words])
    items = []
    for article_id in page:
        item = found[article_id]
        if article_id in passages:
            item["snippet"] = passages[article_id]
        item["found_by"] = "words" if article_id in words else "meaning"
        items.append(item)
    return {"total": len(ordered), "items": items}
