"""Saving one page, one YouTube video or one podcast episode by its address, without making a source of it."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db, removed
from ..connectors import podcast, youtube
from ..jobs import manager
from ..pipeline.scrape import save_link
from ..util import canonical_url
from .sources import normalize_url

router = APIRouter(prefix="/api")


class Link(BaseModel):
    url: str


@router.post("/links")
def save(body: Link) -> dict:
    """Start saving one address. A YouTube video becomes a video, a Spotify episode a podcast episode, anything
    else is read as a page. The job's result carries `article_id`; when the address is in the library already,
    that id comes back at once."""
    url = normalize_url(body.url)
    kind = "video" if youtube.is_youtube(url) else "podcast" if podcast.is_spotify(url) else "article"
    if kind == "podcast":
        ref = podcast.spotify_ref(url)
        if ref and ref[0] == "show":
            raise HTTPException(400, "This is the address of a show, not of one episode. To follow a show, add "
                                     "it as a source in the box above.")
        if not ref or ref[0] != "episode":
            raise HTTPException(400, podcast.NOT_A_PODCAST)
        url = podcast.spotify_url("episode", ref[1])
    elif kind == "video":
        found = youtube.video_id(url)
        if not found:
            raise HTTPException(400, "This is the address of a YouTube channel or playlist, not of one video. "
                                     "To follow a channel, add it as a source in the box above.")
        url = youtube.watch_url(found)
    else:
        url = canonical_url(url)
    stored = db.row("SELECT id FROM articles WHERE url = ?", (url,))
    if stored:
        return {"job_id": None, "article_id": stored["id"], "already": True}
    gone = db.row("SELECT id FROM removed WHERE url = ?", (url,))
    if gone:  # you removed this item earlier and now ask for it by its address: it is put back
        back = removed.restore(gone["id"])
        if back and back["restored"]:
            return {"job_id": None, "article_id": back["article_id"], "already": True, "put_back": True}
    job = manager.submit("save", f"Save: {url}", lambda job: save_link(url, kind, job))
    return {"job_id": job.id, "article_id": None, "already": False}
