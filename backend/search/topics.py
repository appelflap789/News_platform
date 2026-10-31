"""What belongs to a topic, and what its page shows without any AI: timeline, sources, trend, what is next.

An item belongs to a topic when one of three things is true:

* **words** - it matches the topic's term lists (query.py), as before;
* **meaning** - it is close to what the topic is about, in whatever words or language. "What the topic is about"
  is a point in the same space as the embeddings: the topic's name and description, pulled towards its best word
  matches and the items you said belong, and away from the ones you said do not;
* **you** - you said so with "belongs here". "Not this" removes an item whatever the other two say.

Meaning also takes away. A report on diesel prices that names the Strait of Hormuz once matches the words of a
topic on the strait without being about it. Such an item is a **mention**: it stays findable on the topic's
page, but the timeline, the trend and the texts Claude writes are made from the items that are about the topic.

Membership is worked out when it is asked for, so new items are in their topics the moment they are stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .. import db
from . import embed, meaning, query

# How close to the topic an item must be to be collected by meaning. Measured with the multilingual MiniLM
# model on a library of 380 items (October 2026): for a topic such as "Strait of Hormuz" the items about it
# scored 0.38 and up, and the first item that was about something else 0.32.
REACH = {"narrow": 0.50, "balanced": 0.42, "broad": 0.35}
ANCHORS = 10  # the best word matches that pull the topic's point towards the library's own material
ANCHOR_SPREAD = 0.30  # ... except those that are this much further from it than the closest of them
WORD_BONUS = 0.10  # an item that also matches the words ranks a little higher
# A word match further from the topic than this only mentions it. In the same measurement the word matches
# for "Strait of Hormuz" above 0.2 were about the strait, the Gulf or the war around it; those below were
# about diesel prices, Ukraine and European energy.
MENTION_BELOW = 0.20
# Items this close, and close in time, are one entry on the timeline. At 0.68 the same library gave 28 such
# entries: one event in several reports, a paper with its announcement or its translation, reposts.
STORY_SIMILARITY = 0.68
STORY_DAYS = 10
TIMELINE_ITEMS = 600  # how far back the timeline groups
TREND_WEEKS = 26


@dataclass
class Members:
    ids: list[int] = field(default_factory=list)  # the items that are about the topic, best match first
    mentions: list[int] = field(default_factory=list)  # the items that only mention it, best match first
    score: dict[int, float] = field(default_factory=dict)
    why: dict[int, str] = field(default_factory=dict)  # 'words', 'meaning', 'you' or 'mention'
    match: str = ""  # the FTS expression of the term lists
    vector: object = None  # the topic's point in the embedding space, when there is one

    def count(self, why: str) -> int:
        return sum(1 for reason in self.why.values() if reason == why)

    def scope(self, name: str) -> list[int]:
        """'about' (the default everywhere), 'mentions', or 'all'."""
        if name == "mentions":
            return self.mentions
        return self.ids + self.mentions if name == "all" else self.ids


def verdicts(topic_id: int | None) -> dict[int, str]:
    if not topic_id:
        return {}
    return {row["article_id"]: row["verdict"]
            for row in db.rows("SELECT article_id, verdict FROM topic_items WHERE topic_id = ?", (topic_id,))}


def members(topic: dict) -> Members:
    """Every item of a topic. `topic` needs name, description, required_any, terms, by_meaning, reach and,
    when it is a stored topic, id."""
    found = Members(match=query.topic_match(topic["required_any"], topic["terms"]))
    said = verdicts(topic.get("id"))
    by_words = []
    if found.match:
        by_words = [row["id"] for row in db.rows(
            f"SELECT rowid AS id, bm25(articles_fts, {query.WEIGHTS}) AS score FROM articles_fts"
            f" WHERE articles_fts MATCH ? ORDER BY score, rowid DESC", (found.match,))]
    for rank, article_id in enumerate(by_words):
        found.why[article_id] = "words"
        found.score[article_id] = 1.0 - rank / len(by_words)  # replaced below when the item has an embedding

    if embed.ready():
        index = embed.index()
        found.vector = _point(topic, by_words, said, index)
        closeness = index.matrix @ found.vector
        if topic.get("by_meaning", 1):
            threshold = index.bar(REACH.get(topic.get("reach") or "balanced", REACH["balanced"]))
            allowed = None
            if topic["required_any"]:  # a topic about one company or person: the name must still be mentioned
                allowed = {row["id"] for row in db.rows(
                    "SELECT rowid AS id FROM articles_fts WHERE articles_fts MATCH ?",
                    (query.any_of(topic["required_any"]),))}
            for position in embed.np.nonzero(closeness >= threshold)[0]:
                article_id = int(index.ids[position])
                if article_id not in found.why and (allowed is None or article_id in allowed):
                    found.why[article_id] = "meaning"
        # A topic about one name wants every item that names it, so nothing is set aside there.
        aside = index.bar(MENTION_BELOW) if topic.get("by_meaning", 1) and not topic["required_any"] else None
        for article_id in found.why:  # with embeddings, "best match" is closeness to the topic, for every item
            if article_id in index.row:
                close = float(closeness[index.row[article_id]])
                if found.why[article_id] == "words" and aside is not None and close < aside:
                    found.why[article_id] = "mention"
                found.score[article_id] = close + (WORD_BONUS if found.why[article_id] == "words" else 0.0)

    for article_id, verdict in said.items():
        if verdict == "out":
            found.why.pop(article_id, None)
        elif db.scalar("SELECT 1 FROM articles WHERE id = ?", (article_id,)):
            found.why[article_id] = "you"
            found.score[article_id] = found.score.get(article_id, 0.0) + 1.0
    found.score = {article_id: found.score.get(article_id, 0.0) for article_id in found.why}
    ranked = sorted(found.why, key=lambda article_id: (-found.score[article_id], -article_id))
    found.ids = [article_id for article_id in ranked if found.why[article_id] != "mention"]
    found.mentions = [article_id for article_id in ranked if found.why[article_id] == "mention"]
    return found


def _point(topic: dict, by_words: list[int], said: dict[int, str], index: embed.Index):
    """Where the topic sits among the embeddings."""
    np = embed.np
    point = index.place(embed.encode_query(f"{topic['name']}. {topic.get('description') or ''}".strip()))

    def centre(ids: list[int]):
        vectors = index.vectors(ids)
        return vectors.mean(axis=0) if len(vectors) else None

    def unit(vector):
        return vector / (np.linalg.norm(vector) or 1.0)

    # The anchors are the best word matches. One of them may only mention the topic, so the point is first
    # placed with all of them, and then again without the ones that turned out to lie far from it.
    anchors = None
    best = index.vectors([i for i in by_words if said.get(i) != "out" and i in index.row][:ANCHORS])
    if len(best):
        close = best @ unit(point + unit(best.mean(axis=0)))
        anchors = best[close >= close.max() - ANCHOR_SPREAD].mean(axis=0)
    belongs = centre([i for i, verdict in said.items() if verdict == "in"])
    rejected = centre([i for i, verdict in said.items() if verdict == "out"])
    if anchors is not None:
        point = point + anchors / (np.linalg.norm(anchors) or 1.0)
    if belongs is not None:
        point = point + 0.75 * belongs / (np.linalg.norm(belongs) or 1.0)
    if rejected is not None:
        point = point - 0.25 * rejected / (np.linalg.norm(rejected) or 1.0)
    return point / (np.linalg.norm(point) or 1.0)


def facts(ids: list[int]) -> dict[int, dict]:
    """The few columns the page's counts and timeline are built from."""
    found: dict[int, dict] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        for row in db.rows(
                f"SELECT a.id, a.source_id, a.content_type, a.fetched_at,"
                f" COALESCE(NULLIF(a.published_at, ''), a.fetched_at) AS date FROM articles a"
                f" WHERE a.id IN ({marks})", chunk):
            found[row["id"]] = row
    return found


def search(found: Members, *, scope: str = "about", source_id: int | None = None, sort: str = "relevance",
           limit: int = 30, offset: int = 0) -> dict:
    """A page of a topic's items as cards, best match or newest first."""
    wanted = found.scope(scope)
    known = facts(wanted)
    ids = [i for i in wanted if i in known and (not source_id or known[i]["source_id"] == source_id)]
    if sort == "newest":
        ids.sort(key=lambda i: (known[i]["date"], i), reverse=True)
    page = ids[offset:offset + limit]
    rows = meaning.cards(page)
    passages = meaning.snippets(found.match, [i for i in page if found.why[i] in ("words", "mention")])
    items = []
    for article_id in page:
        if article_id in rows:
            item = rows[article_id]
            item["why"] = found.why[article_id]
            if article_id in passages:
                item["snippet"] = passages[article_id]
            items.append(item)
    return {"total": len(ids), "items": items}


def pictures(found: Members, limit: int = 8) -> list[str]:
    """Pictures for a topic's card: those of its newest items that have one. A source gets one picture before
    any source gets a second, so that one site's house style does not fill the card."""
    known = facts(found.ids)
    newest = sorted(known, key=lambda i: (known[i]["date"], i), reverse=True)[:120]
    if not newest:
        return []
    marks = ",".join("?" * len(newest))
    shown = {row["id"]: row for row in db.rows(
        f"SELECT id, source_id, image_url FROM articles WHERE id IN ({marks}) AND image_url != ''", newest)}
    picked: list[str] = []
    sources: set[int] = set()
    for one_per_source in (True, False):
        for article_id in newest:
            row = shown.get(article_id)
            if row is None or row["image_url"] in picked or (one_per_source and row["source_id"] in sources):
                continue
            picked.append(row["image_url"])
            sources.add(row["source_id"])
            if len(picked) == limit:
                return picked
    return picked


def latest(found: Members) -> str:
    """The date of a topic's newest item, or '' when it has none."""
    return max((item["date"] for item in facts(found.ids).values()), default="")


def breakdown(found: Members) -> dict:
    """Which sources and which kinds of content a topic is made of."""
    known = facts(found.ids)
    per_source: dict[int, int] = {}
    per_kind: dict[str, int] = {}
    for item in known.values():
        per_source[item["source_id"]] = per_source.get(item["source_id"], 0) + 1
        per_kind[item["content_type"]] = per_kind.get(item["content_type"], 0) + 1
    names = {row["id"]: row for row in db.rows("SELECT id, name, icon_url FROM sources")}
    sources = [{"id": source_id, "name": names[source_id]["name"], "icon_url": names[source_id]["icon_url"],
                "matches": count}
               for source_id, count in sorted(per_source.items(), key=lambda kv: (-kv[1], kv[0])) if source_id in names]
    kinds = [{"content_type": kind, "n": count} for kind, count in sorted(per_kind.items(), key=lambda kv: -kv[1])]
    return {"sources": sources, "kinds": kinds}


def _day(stamp: str) -> date:
    return date(int(stamp[:4]), int(stamp[5:7]), int(stamp[8:10]))


def new_since(found: Members, since: str) -> set[int]:
    """The items that reached the library after `since` (a timestamp; '' = nothing counts as new)."""
    if not since:
        return set()
    return {article_id for article_id, item in facts(found.ids).items() if item["fetched_at"] > since}


def timeline(found: Members, *, since: str = "", limit: int = 40, offset: int = 0) -> dict:
    """The topic's items by date, newest first. Items that say almost the same thing within a few days
    (one event in several sources, a report and its announcement, a repost) are one entry."""
    known = facts(found.ids)
    newest = sorted(known, key=lambda i: (known[i]["date"], i), reverse=True)[:TIMELINE_ITEMS]
    group = {article_id: article_id for article_id in newest}

    def root(article_id: int) -> int:
        while group[article_id] != article_id:
            group[article_id] = group[group[article_id]]
            article_id = group[article_id]
        return article_id

    if embed.ready():
        index = embed.index()
        embedded = [i for i in newest if i in index.row]
        if len(embedded) > 1:
            vectors = index.vectors(embedded)
            alike = vectors @ vectors.T
            days = [_day(known[i]["date"]).toordinal() for i in embedded]
            for a, b in zip(*embed.np.nonzero(embed.np.triu(alike >= index.bar(STORY_SIMILARITY), k=1))):
                if abs(days[a] - days[b]) <= STORY_DAYS:
                    group[root(embedded[a])] = root(embedded[b])
    stories: dict[int, list[int]] = {}
    for article_id in newest:  # newest first, so every story's items come out newest first too
        stories.setdefault(root(article_id), []).append(article_id)
    ordered = sorted(stories.values(), key=lambda ids: (known[ids[0]]["date"], ids[0]), reverse=True)

    page = ordered[offset:offset + limit]
    rows = meaning.cards([article_id for ids in page for article_id in ids])
    fresh = new_since(found, since)
    entries = []
    for ids in page:
        ids = [i for i in ids if i in rows]
        if not ids:
            continue
        lead = max(ids, key=lambda i: (found.score.get(i, 0.0), i))
        row = rows[lead]
        entries.append({
            "id": lead, "ids": ids, "title": row["title"], "date": known[ids[0]]["date"],
            "first_date": known[ids[-1]]["date"], "source_id": row["source_id"], "source_name": row["source_name"],
            "source_icon": row["source_icon"], "content_type": row["content_type"],
            "summary": " ".join(embed.SHARED_LINE.sub("", row["ai_summary"] or row["summary"]).split()),
            "translated_from": row["translated_from"],
            # the lead item's picture, or the picture of another item of the same story
            "image_url": next((rows[i]["image_url"] for i in [lead, *ids] if rows[i]["image_url"]), ""),
            "why": found.why[lead], "new": any(i in fresh for i in ids),
            "sources": len({rows[i]["source_id"] for i in ids}),
            "more": [{"id": i, "title": rows[i]["title"], "source_name": rows[i]["source_name"],
                      "date": known[i]["date"]} for i in ids if i != lead],
        })
    return {"total": len(ordered), "items": entries}


def trend(found: Members, today: date | None = None) -> dict:
    """How much of the library a topic takes up, week by week, and two comparisons: the last week against the
    four before it (the short run) and the last three months against the three before (the long run).

    Shares are compared, not counts: when a source is added, every topic gets more items, and that is not a
    trend. A comparison is only made when the library itself has enough items in both periods.
    """
    today = today or datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday()) - timedelta(weeks=TREND_WEEKS - 1)
    mine = [_day(item["date"]) for item in facts(found.ids).values()]
    everything = [(_day(row["day"]), row["n"]) for row in db.rows(
        "SELECT SUBSTR(COALESCE(NULLIF(published_at, ''), fetched_at), 1, 10) AS day, COUNT(*) AS n FROM articles"
        " GROUP BY day")]

    weeks = [{"start": (start + timedelta(weeks=n)).isoformat(), "count": 0, "total": 0} for n in range(TREND_WEEKS)]
    for day in mine:
        if start <= day <= today:
            weeks[(day - start).days // 7]["count"] += 1
    for day, count in everything:
        if start <= day <= today:
            weeks[(day - start).days // 7]["total"] += count

    def window(days_ago_from: int, days_ago_to: int) -> tuple[int, int]:
        """(items of the topic, items of the whole library) dated from..to days ago."""
        first, last = today - timedelta(days=days_ago_from), today - timedelta(days=days_ago_to)
        return (sum(1 for day in mine if first <= day <= last),
                sum(count for day, count in everything if first <= day <= last))

    def compare(now: tuple[int, int], before: tuple[int, int], enough: int, up: float, down: float,
                words: tuple[str, str, str]) -> dict:
        result = {"now": now[0], "before": before[0], "label": "", "ratio": None}
        if now[1] < enough or before[1] < enough:
            result["label"] = "too little history"
            return result
        share_now, share_before = now[0] / now[1], before[0] / before[1]
        if not share_before:
            result["label"] = words[0] if now[0] >= 3 else "quiet"
            return result
        result["ratio"] = round(share_now / share_before, 2)
        result["label"] = words[0] if result["ratio"] >= up and now[0] >= 3 else (
            words[2] if result["ratio"] <= down else words[1])
        return result

    dates = sorted(mine)
    return {
        "weeks": weeks,
        "short": compare(window(6, 0), window(34, 7), 30, 1.5, 0.5, ("spiking", "steady", "quieter")),
        "long": compare(window(90, 0), window(181, 91), 100, 1.5, 0.67, ("building", "steady", "fading")),
        "first": dates[0].isoformat() if dates else "",
        "last": dates[-1].isoformat() if dates else "",
    }


def related(point, others: list[tuple[dict, Members]]) -> list[dict]:
    """The other topics, the one closest in meaning first."""
    listed = []
    for topic, found in others:
        closeness = 0.0
        if point is not None and found.vector is not None:
            closeness = float(point @ found.vector)
        listed.append({"id": topic["id"], "name": topic["name"], "matches": len(found.ids),
                       "new": len(new_since(found, topic["visited_at"])), "closeness": round(closeness, 3)})
    return sorted(listed, key=lambda entry: (-entry["closeness"], entry["name"].lower()))
