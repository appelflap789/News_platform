"""Articles: the feed, search, and the reader."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .. import db, removed
from ..ai import client as ai
from ..connectors import reddit
from ..jobs import manager
from ..pipeline import comments, translate
from ..search import meaning, query
from .system import start_embedding

router = APIRouter(prefix="/api")


@router.get("/articles")
def list_articles(
    q: str = "",
    source_id: int | None = None,
    content_type: str = "",
    sort: str = Query("newest", pattern="^(newest|relevance)$"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    favorites: bool = False,
    saved: str = Query("", pattern="^(|all|article|video|podcast)$"),  # the single items saved by their address
) -> dict:
    if not q.strip() or favorites or saved:
        return query.search(query.text_match(q) if q.strip() else "", source_id=source_id, content_type=content_type,
                            sort=sort, limit=limit, offset=offset, favorites=favorites, saved=saved)
    return meaning.search(q.strip(), source_id=source_id, content_type=content_type, sort=sort, limit=limit,
                          offset=offset)


@router.get("/articles/{article_id}")
def get_article(article_id: int) -> dict:
    article = db.row(
        """SELECT a.*, s.name AS source_name, s.icon_url AS source_icon
           FROM articles a JOIN sources s ON s.id = a.source_id WHERE a.id = ?""",
        (article_id,),
    )
    if article is None:
        raise HTTPException(404, "Article not found.")
    # an item from Reddit: the post whose comments can be summed up (pipeline/comments.py); '' for any other
    article["discussion_url"] = reddit.discussion_url(article["url"], article["text"], article["original_text"])
    article["comments"] = json.loads(article["comments"] or "[]")  # [{author, text}], highest voted first
    # the reader's Translate button: what it costs and how long it takes; None for an item in English
    article["translation"] = translate.offer(article)
    return article


class Favorite(BaseModel):
    on: bool = True


@router.put("/articles/{article_id}/favorite")
def favorite(article_id: int, body: Favorite) -> dict:
    """Star an item, or take the star away. Favorites have a shelf of their own on Home."""
    changed = db.execute("UPDATE articles SET favorite_at = ? WHERE id = ?",
                         (db.now() if body.on else "", article_id)).rowcount
    if not changed:
        raise HTTPException(404, "Article not found.")
    return {"favorite_at": db.scalar("SELECT favorite_at FROM articles WHERE id = ?", (article_id,))}


@router.post("/articles/{article_id}/comments")
def summarise_comments(article_id: int) -> dict:
    """Read the comments under the Reddit post this item belongs to and have Claude sum them up, now."""
    article = db.row("SELECT id, source_id, url, title, text, original_text FROM articles WHERE id = ?", (article_id,))
    if article is None:
        raise HTTPException(404, "Article not found.")
    if not reddit.discussion_url(article["url"], article["text"], article["original_text"]):
        raise HTTPException(400, "This item did not come from Reddit, so there are no comments to read.")
    if not ai.available():
        raise HTTPException(400, "Summing up comments needs an Anthropic API key. Add one on the Settings page.")
    job = manager.submit("comments", f"Comments: {article['title'][:70]}",
                         lambda job: comments.summarise(article_id, job), source_id=article["source_id"])
    return {"job_id": job.id}


@router.post("/articles/{article_id}/translate")
def translate_one(article_id: int) -> dict:
    """Translate this one item into English, now, whatever its length."""
    article = db.row("SELECT id, source_id, title, translated_from FROM articles WHERE id = ?", (article_id,))
    if article is None:
        raise HTTPException(404, "Article not found.")
    if article["translated_from"]:
        raise HTTPException(409, "This item has been translated already.")
    if not ai.available():
        raise HTTPException(400, "Translating needs an Anthropic API key. Add one on the Settings page.")
    if manager.active_for_source(article["source_id"], ("translate",)):
        raise HTTPException(409, "Its source is being translated right now. Try again when that run has finished.")
    job = manager.submit("translate", f"Translate: {article['title'][:70]}",
                         lambda job: translate.translate_one(article_id, job), source_id=article["source_id"])
    return {"job_id": job.id}


@router.get("/articles/{article_id}/similar")
def similar_articles(article_id: int, limit: int = Query(6, ge=1, le=20)) -> dict:
    """Items about the same thing, closest first. Empty when the item has no embedding yet."""
    if db.scalar("SELECT 1 FROM articles WHERE id = ?", (article_id,)) is None:
        raise HTTPException(404, "Article not found.")
    return {"items": meaning.similar(article_id, limit)}


@router.delete("/articles/{article_id}")
def delete_article(article_id: int) -> dict:
    """Remove one item from the library. Its address is remembered, so no scrape stores it again, and the item
    is kept in the list of removed items, from where it can be put back as it was."""
    gone = removed.remove([article_id])
    if not gone:
        raise HTTPException(404, "Article not found.")
    return {"deleted": True, "removed_id": gone[0]["id"], "title": gone[0]["title"]}


@router.get("/removed")
def list_removed(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    """The items you removed, the last one first."""
    return removed.listing(limit, offset)


@router.post("/removed/{removed_id}/restore")
def restore_removed(removed_id: int) -> dict:
    """Put a removed item back as it was. When its source no longer exists that cannot be done; the item is
    then only forgotten (`restored` is False), so that a source that lists it collects it again."""
    back = removed.restore(removed_id)
    if back is None:
        raise HTTPException(404, "This item is not in the list of removed items.")
    if back["restored"]:
        start_embedding()  # does nothing unless the item came back without an embedding of the current model
    return back
