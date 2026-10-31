"""Turn search words and topic term lists into FTS5 queries, and run them.

A topic has two lists:
* `required_any` - an article must mention at least one of these (use for a
  specific company, person or programme; leave empty for broad topics);
* `terms`        - an article must mention at least one of these, and the more
  and the more prominently it does, the higher it ranks.
"""

from __future__ import annotations

import re

from .. import db

# Private-use characters around matched words in snippets; the frontend turns them into highlights.
MARK_OPEN, MARK_CLOSE = "", ""
# Column weights for BM25: title, summary, ai_summary, tags, text.
WEIGHTS = "10.0, 4.0, 4.0, 6.0, 1.0"
PREFIX_MIN_LENGTH = 4

CARD_COLUMNS = """a.id, a.source_id, a.feed_name, a.url, a.title, a.author, a.published_at, a.fetched_at,
                  a.summary, a.ai_summary, a.image_url, a.pdf_url, a.content_type, a.language, a.tags,
                  a.word_count, a.is_partial, a.translated_from, a.video_id, a.views, a.duration_seconds,
                  a.favorite_at, s.name AS source_name, s.icon_url AS source_icon"""
NEWEST = "COALESCE(NULLIF(a.published_at, ''), a.fetched_at) DESC, a.id DESC"


def term_expression(term: str) -> str:
    """One search term as FTS5 syntax: a word matches by prefix ('drone' finds 'drones'), several words as a phrase."""
    tokens = re.findall(r"\w+", term, re.UNICODE)
    if not tokens:
        return ""
    if len(tokens) == 1:
        token = tokens[0]
        return f'"{token}"*' if len(token) >= PREFIX_MIN_LENGTH else f'"{token}"'
    return '"' + " ".join(tokens) + '"'


def any_of(terms: list[str]) -> str:
    expressions = list(dict.fromkeys(e for e in (term_expression(t) for t in terms) if e))
    return "(" + " OR ".join(expressions) + ")" if expressions else ""


def topic_match(required_any: list[str], terms: list[str]) -> str:
    return " AND ".join(group for group in (any_of(required_any), any_of(terms)) if group)


def text_match(query: str) -> str:
    """A search-box query: every word must appear; "quoted words" must appear together."""
    parts = re.findall(r'"([^"]+)"|(\S+)', query)
    expressions = [term_expression(phrase or word) for phrase, word in parts]
    return " AND ".join(e for e in expressions if e)


def search(match: str, *, source_id: int | None = None, content_type: str = "", sort: str = "relevance",
           limit: int = 30, offset: int = 0, favorites: bool = False) -> dict:
    """Articles matching an FTS5 expression (or all articles when `match` is empty). `favorites` keeps only
    the ones you starred, the last one you starred first."""
    where, params = [], []
    if favorites:
        where.append("a.favorite_at != ''")
    if match:
        where.append("articles_fts MATCH ?")
        params.append(match)
    if source_id:
        where.append("a.source_id = ?")
        params.append(source_id)
    if content_type:
        where.append("a.content_type = ?")
        params.append(content_type)
    condition = ("WHERE " + " AND ".join(where)) if where else ""

    if match:
        base = "FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid JOIN sources s ON s.id = a.source_id"
        extra = (f", bm25(articles_fts, {WEIGHTS}) AS score,"
                 f" snippet(articles_fts, -1, '{MARK_OPEN}', '{MARK_CLOSE}', ' … ', 28) AS snippet")
        order = "score, a.id DESC" if sort == "relevance" else NEWEST
    else:
        base = "FROM articles a JOIN sources s ON s.id = a.source_id"
        extra = ""
        order = "a.favorite_at DESC, a.id DESC" if favorites else NEWEST
    total = db.scalar(f"SELECT COUNT(*) {base} {condition}", params)
    items = db.rows(
        f"SELECT {CARD_COLUMNS}{extra} {base} {condition} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    return {"total": total, "items": items}


def count(match: str) -> int:
    if not match:
        return 0
    return db.scalar("SELECT COUNT(*) FROM articles_fts WHERE articles_fts MATCH ?", (match,)) or 0


def sources_for(match: str) -> list[dict]:
    """Which sources cover a topic, best-covered first."""
    if not match:
        return []
    return db.rows(
        """SELECT s.id, s.name, s.icon_url, COUNT(*) AS matches
           FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid JOIN sources s ON s.id = a.source_id
           WHERE articles_fts MATCH ? GROUP BY s.id ORDER BY matches DESC""",
        (match,),
    )
