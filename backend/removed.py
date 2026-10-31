"""Items you removed from the library yourself.

Removing an item takes it out of everything (the feed, search, the topics) and remembers its address, so that
no scrape stores it again: a source that still lists it treats it as known. The item itself is kept here as it
was, with its translation, AI summary, transcript and embedding, so that putting it back loses nothing and
costs nothing.

This is not the same as `left_out` (items a source never stored because their page could not be read): that
list belongs to one source and is the scraper's doing; this one is yours and holds for every source.
"""

from __future__ import annotations

import base64
import json

from . import db


def remove(article_ids: list[int]) -> list[dict]:
    """Take these items out of the library. Returns an entry for each one that was there."""
    done = []
    for article_id in article_ids:
        with db.transaction():
            article = db.row("SELECT a.*, s.name AS source_name FROM articles a JOIN sources s ON s.id = a.source_id"
                             " WHERE a.id = ?", (article_id,))
            if article is None:
                continue
            source_name = article.pop("source_name")
            kept = {"article": article, "verdicts": db.rows(
                "SELECT topic_id, verdict FROM topic_items WHERE article_id = ?", (article_id,))}
            embedding = db.connect().execute(
                "SELECT model, vector FROM embeddings WHERE article_id = ?", (article_id,)).fetchone()
            if embedding:
                kept["embedding"] = {"model": embedding["model"],
                                     "vector": base64.b64encode(embedding["vector"]).decode("ascii")}
            db.execute(
                "INSERT INTO removed(url, source_id, source_name, title, content_type, published_at, removed_at, item)"
                " VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET source_id = excluded.source_id,"
                " source_name = excluded.source_name, title = excluded.title, content_type = excluded.content_type,"
                " published_at = excluded.published_at, removed_at = excluded.removed_at, item = excluded.item",
                (article["url"], article["source_id"], source_name, article["title"], article["content_type"],
                 article["published_at"], db.now(), json.dumps(kept)))
            db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
            done.append({"id": db.scalar("SELECT id FROM removed WHERE url = ?", (article["url"],)),
                         "article_id": article_id, "title": article["title"], "url": article["url"]})
    return done


def restore(removed_id: int) -> dict | None:
    """Put a removed item back as it was; None when the list has no such entry.

    When the item cannot be put back (its source was deleted since), its address is forgotten instead:
    `restored` is False, and a source that lists the item will collect it again."""
    entry = db.row("SELECT * FROM removed WHERE id = ?", (removed_id,))
    if entry is None:
        return None
    kept = json.loads(entry["item"]) if entry["item"] else None
    with db.transaction():
        article_id = db.scalar("SELECT id FROM articles WHERE url = ?", (entry["url"],))
        if article_id is None and kept and db.scalar(
                "SELECT 1 FROM sources WHERE id = ?", (kept["article"]["source_id"],)):
            article_id = _put_back(kept)
        db.execute("DELETE FROM removed WHERE id = ?", (removed_id,))
    return {"restored": article_id is not None, "article_id": article_id, "title": entry["title"]}


def _put_back(kept: dict) -> int:
    article = kept["article"]
    # Only the columns the table has: one may have been added since the item was removed.
    columns = [column["name"] for column in db.rows("PRAGMA table_info(articles)") if column["name"] in article]
    if db.scalar("SELECT 1 FROM articles WHERE id = ?", (article["id"],)):
        columns.remove("id")  # its number was given away; it gets a new one
    article_id = db.execute(
        f"INSERT INTO articles({', '.join(columns)}) VALUES({', '.join('?' * len(columns))})",
        [article[column] for column in columns]).lastrowid
    for said in kept.get("verdicts", []):  # what you said about it on your topics, where those still exist
        db.execute("INSERT OR IGNORE INTO topic_items(topic_id, article_id, verdict)"
                   " SELECT id, ?, ? FROM topics WHERE id = ?", (article_id, said["verdict"], said["topic_id"]))
    embedding = kept.get("embedding")
    if embedding:
        db.execute("INSERT OR REPLACE INTO embeddings(article_id, model, vector) VALUES(?,?,?)",
                   (article_id, embedding["model"], base64.b64decode(embedding["vector"])))
    return article_id


def among(urls: list[str]) -> set[str]:
    """Which of these addresses you removed."""
    found: set[str] = set()
    for start in range(0, len(urls), 400):
        chunk = urls[start:start + 400]
        marks = ",".join("?" * len(chunk))
        found.update(row["url"] for row in db.rows(f"SELECT url FROM removed WHERE url IN ({marks})", chunk))
    return found


def listing(limit: int = 50, offset: int = 0) -> dict:
    """The removed items, the last one removed first. `kept` says whether the item can be put back as it was."""
    items = db.rows(
        "SELECT id, url, title, source_id, source_name, content_type, published_at, removed_at,"
        " (item != '' AND source_id IS NOT NULL) AS kept FROM removed ORDER BY removed_at DESC, id DESC"
        " LIMIT ? OFFSET ?", (limit, offset))
    for item in items:
        item["kept"] = bool(item["kept"])
    return {"total": db.scalar("SELECT COUNT(*) FROM removed"), "items": items}


def source_deleted(source_id: int) -> None:
    """Call before a source is deleted. What you removed from it stays removed (adding the source again does
    not bring those items back), but the kept copies go: an item cannot be put back without its source."""
    db.execute("UPDATE removed SET item = '' WHERE source_id = ?", (source_id,))
