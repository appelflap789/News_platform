"""Sources: analyse a new one, save its recipe, scrape it, edit it."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import db, removed
from ..ai import client as ai
from ..analyzers import analyzers
from ..connectors import Context, connectors
from ..jobs import Job, manager
from ..pipeline.enrich import enrich_backlog
from ..pipeline.enrich import prices as label_prices
from ..pipeline.scrape import preview_article, preview_feed, remember_left_out, scrape_source
from ..pipeline import videos
from ..pipeline.translate import prices, translate_backlog, waiting_for
from ..schemas import FeedRecipe, Recipe, validate_recipe
from ..util import host_of

router = APIRouter(prefix="/api")

SOURCE_JOBS = ("scrape", "enrich", "translate", "videos", "save")
LIST_SQL = """
    SELECT s.id, s.name, s.url, s.description, s.language, s.icon_url, s.analyzer, s.enrich_enabled,
           s.skip_walled, s.write_videos, s.interval_minutes, s.created_at, s.last_scraped_at, s.last_error,
           s.recipe,
           (SELECT COUNT(*) FROM articles a WHERE a.source_id = s.id) AS article_count,
           (SELECT MAX(COALESCE(NULLIF(a.published_at, ''), a.fetched_at)) FROM articles a
             WHERE a.source_id = s.id) AS latest_article
    FROM sources s
"""


class AnalyzeRequest(BaseModel):
    url: str
    analyzer: str = "claude"
    hint: str = ""


class SourceCreate(BaseModel):
    url: str
    recipe: Recipe
    analyzer: str = ""
    enrich_enabled: bool = False
    skip_walled: bool = False  # leave out items whose own page is behind a login or paywall, or refuses
    write_videos: bool = True  # write out what is said in videos and write them up as articles
    interval_minutes: int = Field(0, ge=0)
    scrape_now: bool = True
    first_limit: int = Field(0, ge=0, le=100_000)  # the first scrape takes at most this many, newest first (0 = pages)


class SourcePatch(BaseModel):
    recipe: Recipe | None = None
    enrich_enabled: bool | None = None
    skip_walled: bool | None = None
    write_videos: bool | None = None
    interval_minutes: int | None = Field(None, ge=0)


class ScrapeRequest(BaseModel):
    deep: bool = False
    limit: int = Field(0, ge=0, le=100_000)  # a deep scrape: stop when this many new items are stored (0 = all)


class FeedTest(BaseModel):
    feed: FeedRecipe
    pages: int = Field(1, ge=1, le=3)


class ArticleTest(BaseModel):
    url: str
    article: dict[str, str] = Field(default_factory=dict)


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        raise HTTPException(400, "Enter a web address.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    host = urlsplit(url).hostname or ""
    if "." not in host:
        raise HTTPException(400, f"'{url}' does not look like a web address.")
    return url


def _present(source: dict, with_recipe: bool = False) -> dict:
    recipe = json.loads(source.pop("recipe"))
    source["enrich_enabled"] = bool(source["enrich_enabled"])
    source["skip_walled"] = bool(source["skip_walled"])
    source["write_videos"] = bool(source["write_videos"])
    source["feeds"] = [
        {"name": f["name"], "connector": f["connector"], "enabled": f.get("enabled", True),
         "content_type": f.get("content_type", "article")}
        for f in recipe.get("feeds", [])
    ]
    # A source of single saved items has no feeds to scrape. And the sidebar sorts sources into two kinds.
    source["saved"] = source["analyzer"].removeprefix("saved-") if source["analyzer"].startswith("saved-") else ""
    connected = {f["connector"] for f in source["feeds"]}
    source["kind"] = ("videos" if source["saved"] == "video" or connected == {"youtube"} else
                      "podcasts" if source["saved"] == "podcast" or connected == {"podcast"} else "articles")
    job = manager.active_for_source(source["id"], SOURCE_JOBS)
    source["active_job"] = job.id if job else None
    if with_recipe:
        source["recipe"] = recipe
    return source


def _get(source_id: int) -> dict:
    source = db.row(LIST_SQL + " WHERE s.id = ?", (source_id,))
    if source is None:
        raise HTTPException(404, "Source not found.")
    return source


def _checked(recipe: Recipe) -> Recipe:
    try:
        validate_recipe(recipe)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    return recipe


def _start_analysis(url: str, analyzer_name: str, hint: str, source_id: int | None = None) -> Job:
    if analyzer_name not in analyzers.names():
        raise HTTPException(400, f"Unknown analyzer '{analyzer_name}'.")
    analyzer = analyzers.get(analyzer_name)
    if analyzer.requires_ai and not ai.available():
        raise HTTPException(400, "Claude analysis needs an Anthropic API key. Add one on the Settings page, "
                                 "or use Quick detect.")

    def run(job: Job) -> dict:
        return analyzer.analyze(url, hint, job, Context()).as_dict(analyzer_name, url)

    return manager.submit("analyze", f"Analyse {host_of(url)}", run, source_id=source_id)


def _start_scrape(source_id: int, name: str, deep: bool, title: str = "", limit: int = 0) -> Job:
    busy = manager.active_for_source(source_id, SOURCE_JOBS)
    if busy:
        raise HTTPException(409, "This source is already being worked on.")
    how_far = f" ({limit:,} more)" if deep and limit else f" (the newest {limit:,})" if limit else ""
    title = title or f"{'Deep scrape' if deep else 'Scrape'}{how_far}: {name}"
    return manager.submit("scrape", title, lambda job: scrape_source(source_id, job, deep=deep, limit=limit),
                          source_id=source_id)


# --- analysis and recipe testing --------------------------------------------------------

@router.post("/sources/analyze")
def analyze(request: AnalyzeRequest) -> dict:
    job = _start_analysis(normalize_url(request.url), request.analyzer, request.hint)
    return {"job_id": job.id}


@router.post("/recipes/test-feed")
def test_feed(request: FeedTest) -> dict:
    _checked(Recipe(site_name="test", feeds=[request.feed]))
    return preview_feed(request.feed, pages=request.pages)


@router.post("/recipes/test-article")
def test_article(request: ArticleTest) -> dict:
    return preview_article(normalize_url(request.url), request.article)


# --- sources ------------------------------------------------------------------------------

@router.get("/sources")
def list_sources() -> list[dict]:
    return [_present(s) for s in db.rows(LIST_SQL + " ORDER BY s.name COLLATE NOCASE")]


@router.post("/sources")
def create_source(request: SourceCreate) -> dict:
    recipe = _checked(request.recipe)
    cursor = db.execute(
        """INSERT INTO sources(name, url, description, language, icon_url, recipe, analyzer, enrich_enabled,
                               skip_walled, write_videos, interval_minutes, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (recipe.site_name.strip(), normalize_url(request.url), recipe.description, recipe.language, recipe.icon_url,
         recipe.model_dump_json(), request.analyzer, int(request.enrich_enabled), int(request.skip_walled),
         int(request.write_videos), request.interval_minutes, db.now()),
    )
    source_id = cursor.lastrowid
    job = None
    if request.scrape_now and any(feed.enabled for feed in recipe.feeds):
        job = _start_scrape(source_id, recipe.site_name, deep=False, limit=request.first_limit)
    return {"id": source_id, "job_id": job.id if job else None}


@router.get("/sources/{source_id}")
def get_source(source_id: int) -> dict:
    source = _present(_get(source_id), with_recipe=True)
    source["feed_counts"] = {
        r["feed_name"]: r["n"]
        for r in db.rows("SELECT feed_name, COUNT(*) AS n FROM articles WHERE source_id = ? GROUP BY feed_name",
                         (source_id,))
    }
    source["pending_enrichment"] = db.scalar(
        "SELECT COUNT(*) FROM articles WHERE source_id = ? AND enriched_at = ''", (source_id,))
    source["labels"] = label_prices()
    source["left_out"] = {
        "count": db.scalar("SELECT COUNT(*) FROM left_out WHERE source_id = ?", (source_id,)),
        "recent": db.rows("SELECT url, title, reason, at FROM left_out WHERE source_id = ? ORDER BY at DESC, url"
                          " LIMIT 12", (source_id,)),
    }
    source["partial_stored"] = len(_partial_items(source_id, source["recipe"]))
    source["videos"] = {**videos.prices(), **videos.waiting(source_id)}
    # what the Translate button next to Update would do; the language is told from the words, for nothing
    source["translation"] = {**prices(), "waiting": waiting_for(source_id)}
    return source


@router.patch("/sources/{source_id}")
def update_source(source_id: int, patch: SourcePatch) -> dict:
    _get(source_id)
    if patch.recipe is not None:
        recipe = _checked(patch.recipe)
        db.execute(
            "UPDATE sources SET recipe = ?, name = ?, description = ?, language = ?, icon_url = ? WHERE id = ?",
            (recipe.model_dump_json(), recipe.site_name.strip(), recipe.description, recipe.language,
             recipe.icon_url, source_id),
        )
    if patch.enrich_enabled is not None:
        db.execute("UPDATE sources SET enrich_enabled = ? WHERE id = ?", (int(patch.enrich_enabled), source_id))
    if patch.skip_walled is not None:
        db.execute("UPDATE sources SET skip_walled = ? WHERE id = ?", (int(patch.skip_walled), source_id))
    if patch.write_videos is not None:
        db.execute("UPDATE sources SET write_videos = ? WHERE id = ?", (int(patch.write_videos), source_id))
    if patch.interval_minutes is not None:
        db.execute("UPDATE sources SET interval_minutes = ? WHERE id = ?", (patch.interval_minutes, source_id))
    return get_source(source_id)


@router.delete("/sources/{source_id}")
def delete_source(source_id: int) -> dict:
    _get(source_id)
    if manager.active_for_source(source_id, SOURCE_JOBS):
        raise HTTPException(409, "Stop the running job for this source before deleting it.")
    removed.source_deleted(source_id)
    deleted = db.execute("DELETE FROM articles WHERE source_id = ?", (source_id,)).rowcount
    db.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    return {"deleted": True, "articles_removed": deleted}


def _partial_items(source_id: int, recipe: dict) -> list[dict]:
    """The stored items of which only the lines in front of a login, a paywall or a refusal could be read.
    A feed that is set up to store teasers without opening the items is not counted: nothing went wrong there."""
    opening = []
    for feed in Recipe.model_validate(recipe).feeds:
        if feed.connector in connectors.names() and connectors.get(feed.connector).opens_items(feed):
            opening.append(feed.name)
    if not opening:
        return []
    marks = ",".join("?" * len(opening))
    return db.rows(f"SELECT id, url, title FROM articles WHERE source_id = ? AND is_partial = 1"
                   f" AND feed_name IN ({marks})", [source_id, *opening])


@router.post("/sources/{source_id}/left-out/forget")
def forget_left_out(source_id: int) -> dict:
    """Forget which items were left out, so that the next scrape opens them again."""
    _get(source_id)
    return {"forgotten": db.execute("DELETE FROM left_out WHERE source_id = ?", (source_id,)).rowcount}


@router.post("/sources/{source_id}/partial/remove")
def remove_partial(source_id: int) -> dict:
    """Delete the partial items stored before the source was set to leave them out. They are remembered as
    left out, so they do not come back with the next scrape."""
    source = _present(_get(source_id), with_recipe=True)
    if manager.active_for_source(source_id, SOURCE_JOBS):
        raise HTTPException(409, "Wait until the running job for this source has finished.")
    partial = _partial_items(source_id, source["recipe"])
    for article in partial:
        remember_left_out(source_id, article["url"], article["title"],
                          "only the lines in front of a login, a paywall or a refusal had been stored")
        db.execute("DELETE FROM articles WHERE id = ?", (article["id"],))
    return {"removed": len(partial)}


@router.post("/sources/{source_id}/scrape")
def scrape(source_id: int, request: ScrapeRequest) -> dict:
    source = _get(source_id)
    return {"job_id": _start_scrape(source_id, source["name"], request.deep, limit=request.limit).id}


@router.post("/sources/{source_id}/enrich")
def enrich(source_id: int) -> dict:
    source = _get(source_id)
    if not ai.available():
        raise HTTPException(400, "AI summaries need an Anthropic API key. Add one on the Settings page.")
    if manager.active_for_source(source_id, SOURCE_JOBS):
        raise HTTPException(409, "This source is already being worked on.")
    job = manager.submit("enrich", f"Summarise and tag: {source['name']}",
                         lambda job: enrich_backlog(source_id, job), source_id=source_id)
    return {"job_id": job.id}


@router.post("/sources/{source_id}/translate")
def translate(source_id: int) -> dict:
    """Translate the items of this source that are not in English and not too long to read (Settings)."""
    source = _get(source_id)
    if not ai.available():
        raise HTTPException(400, "Translating needs an Anthropic API key. Add one on the Settings page.")
    if manager.active_for_source(source_id, SOURCE_JOBS):
        raise HTTPException(409, "This source is already being worked on.")
    job = manager.submit("translate", f"Translate: {source['name']}",
                         lambda job: translate_backlog(source_id, job), source_id=source_id)
    return {"job_id": job.id}


class VideosRequest(BaseModel):
    retry: bool = False  # also try the videos again that could not be written out before
    everything: bool = False  # all that is waiting, not only the number one run does


@router.post("/sources/{source_id}/videos")
def write_videos(source_id: int, request: VideosRequest) -> dict:
    """Write out and write up the videos or podcast episodes of this source that are still waiting: as many
    as one run does, or with `everything` all of them."""
    source = _get(source_id)
    if manager.active_for_source(source_id, SOURCE_JOBS):
        raise HTTPException(409, "A job is already running for this source.")
    job = manager.submit(
        "videos", f"Transcribe and summarise: {source['name']}",
        lambda job: videos.backlog(source_id, job, retry=request.retry, everything=request.everything),
        source_id=source_id)
    return {"job_id": job.id}


@router.post("/articles/{article_id}/write")
def write_one(article_id: int) -> dict:
    """Write out and write up one video or one podcast episode, now."""
    article = db.row(f"SELECT id, source_id, title, written_at FROM articles WHERE id = ? AND {videos.RECORDING}",
                     (article_id,))
    if article is None:
        raise HTTPException(404, "This is not a video or a podcast episode in your library.")
    if article["written_at"]:
        raise HTTPException(409, "This one has been written up already.")
    if manager.active_for_source(article["source_id"], SOURCE_JOBS):
        raise HTTPException(409, "Its source is being worked on right now. Try again when that run has finished.")
    job = manager.submit("videos", f"Transcribe and summarise: {article['title'][:70]}",
                         lambda job: videos.one(article_id, job), source_id=article["source_id"])
    return {"job_id": job.id}


@router.post("/sources/{source_id}/reanalyze")
def reanalyze(source_id: int, request: AnalyzeRequest) -> dict:
    """Analyse an existing source again. The result is a draft; the dashboard applies it with PATCH."""
    source = _get(source_id)
    url = normalize_url(request.url or source["url"])
    return {"job_id": _start_analysis(url, request.analyzer, request.hint, source_id=source_id).id}
