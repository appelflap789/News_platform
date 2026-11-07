"""Watching the signposts: free, on this computer, after every scrape and whenever a foresight's page is read.

A signpost is something a news item would report if a consequence were happening (or not). An item that reached
the library after the signpost was made matches it when it is close to the signpost in meaning, or a little
less close and also contains one of its search terms. Only recent items count (dated within `FRESH_DAYS`): a deep
scrape of an archive brings in old items, and those are not news of what is happening now.

When a signpost is made, the items of the last `EARLIER_DAYS` are looked at too. They are kept as "earlier": they
were in the library already, so they tell how well the signpost is worded rather than that something happened.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ... import db
from ...search import embed, query
from . import store

# Measured with the multilingual MiniLM model on a copy of the owner's library (1,264 items, 31 October 2026),
# with the 20 signposts Claude wrote for two foresights. In meaning alone, items between 0.50 and 0.60 were often
# about something else (a swimming robot for "care robots in Japan", 0.51; a list of failed AI start-ups for
# "elder-care robot pilots cancelled", 0.55), and meaning cannot tell a signpost from its opposite ("Diesel at $170"
# scored 0.60 against "diesel prices fall back"); at 0.62 and over they were on the subject. An item that also
# contains a search term of the signpost was on the subject down to about 0.30 ("US pulls diplomats from Saudi
# Arabia as it readies Iran strikes after midterms", 0.32). A match says an item may bear on a consequence; which
# way it points is for the re-check to say.
CLOSE = 0.62  # in meaning alone
WITH_WORDS = 0.30  # an item that also contains one of the signpost's search terms
FRESH_DAYS = 30
EARLIER_DAYS = 14


def _ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _candidates(after: str, dated_from: str) -> list[dict]:
    return db.rows(
        "SELECT id, fetched_at FROM articles WHERE fetched_at >= ?"  # the same second again: repeats are dropped
        " AND COALESCE(NULLIF(published_at, ''), fetched_at) >= ? ORDER BY fetched_at", (after, dated_from))


def matches(signpost: dict, ids: list[int]) -> list[int]:
    """The items among `ids` that match a signpost."""
    if not ids:
        return []
    words: set[int] = set()
    match = query.any_of(signpost["terms"])
    if match:
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            words |= {row["id"] for row in db.rows(
                f"SELECT rowid AS id FROM articles_fts WHERE articles_fts MATCH ?"
                f" AND rowid IN ({','.join('?' * len(chunk))})", [match, *chunk])}
    if not embed.ready():
        return [i for i in ids if i in words]
    index = embed.index()
    present = [i for i in ids if i in index.row]
    if not present:
        return []
    closeness = index.vectors(present) @ index.place(embed.encode_query(signpost["text"]))
    return [i for i, close in zip(present, closeness)
            if close >= index.bar(CLOSE) or (i in words and close >= index.bar(WITH_WORDS))]


def check(signposts: list[dict], *, earlier: bool = False) -> int:
    """Look at what reached the library since each signpost was last looked at. With `earlier`, a signpost that
    was never looked at also looks at the items of the last days, which it keeps as earlier. Returns how many
    new matches there were (earlier ones not counted)."""
    if not signposts:
        return 0
    waiting_on_embedding = embed.ready() and bool(embed.pending())
    found_new = 0
    for signpost in signposts:
        never_looked_at = not signpost["seen"] and signpost["checked_through"] == signpost["created_at"]
        if earlier and never_looked_at:
            before = [row["id"] for row in db.rows(
                "SELECT id FROM articles WHERE COALESCE(NULLIF(published_at, ''), fetched_at) >= ?"
                " AND fetched_at <= ?", (_ago(EARLIER_DAYS), signpost["created_at"]))]
            hits = matches(signpost, before)
            if hits:
                stamps = {row["id"]: row["fetched_at"] for row in db.rows(
                    f"SELECT id, fetched_at FROM articles WHERE id IN ({','.join('?' * len(hits))})", hits)}
                signpost["seen"] = [{"id": i, "at": stamps[i], "earlier": True} for i in hits]
                store.update_signpost(signpost["id"], seen=signpost["seen"])
        rows = _candidates(signpost["checked_through"], _ago(FRESH_DAYS))
        if not rows:
            continue
        through = rows[-1]["fetched_at"]
        if waiting_on_embedding:  # an item without its embedding yet is looked at again next time
            index = embed.index()
            unembedded = [row["fetched_at"] for row in rows if row["id"] not in index.row]
            if unembedded:
                rows = [row for row in rows if row["fetched_at"] < unembedded[0]]
                through = rows[-1]["fetched_at"] if rows else signpost["checked_through"]
        known = {hit["id"] for hit in signpost["seen"]}
        stamps = {row["id"]: row["fetched_at"] for row in rows}
        hits = [i for i in matches(signpost, list(stamps)) if i not in known]
        signpost["seen"] = signpost["seen"] + [{"id": i, "at": stamps[i], "earlier": False} for i in hits]
        found_new += len(hits)
        store.update_signpost(signpost["id"], seen=signpost["seen"], checked_through=through)
    return found_new


def check_foresight(foresight_id: int, *, earlier: bool = False) -> int:
    return check(store.signposts(foresight_id), earlier=earlier)


def after_scrape(job) -> dict | None:
    """The add-on's step at the end of a scrape (backend/addons): match the new items to every signpost."""
    signposts = store.signposts()
    if not signposts:
        return None
    seen = check(signposts)
    if seen:
        names = {row["id"]: row["name"] for row in db.rows("SELECT id, name FROM foresights")}
        touched = sorted({names.get(s["foresight_id"], "") for s in signposts
                          if any(not hit["earlier"] and hit["at"] > s["checked_through"] for hit in s["seen"])} - {""})
        job.log(f"Foresight: {seen} new item{'s' if seen != 1 else ''} matched a signpost"
                + (f" ({', '.join(touched)})." if touched else "."))
    return {"signposts_seen": seen}
