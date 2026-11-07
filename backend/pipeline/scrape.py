"""Run a recipe: list a source's feeds, open what is new, store it."""

from __future__ import annotations

from .. import config, db, removed
from ..connectors import Connector, Context, Item, connectors
from ..errors import ScrapeError
from ..extractors import Extracted, ExtractError, pick
from ..fetchers import FetchError
from ..jobs import Job, JobError
from ..schemas import FeedRecipe, Recipe
from ..util import better_date, host_of, html_to_text, truncate, word_count

GENERIC_TYPES = ("article", "news", "other")
# Answers after which asking again next time is pointless: a login or payment is wanted, the scraper is not
# welcome, or the page is gone. (429 and 503 also turn a request away, but only for now.)
CLOSED = {401, 402, 403, 404, 410, 451}
# A deep scrape that was told how many items to bring is bounded by that number, not by a number of listing
# pages. This many pages is only the net under it, for a listing that never ends and never has anything new.
PAGES_FOR_A_NUMBER = 5000


class LeftOut(ScrapeError):
    """An item is not stored: its own page could not be read (a login, a paywall, a refusal) and its source
    is set to leave such items out. `lasting` is False when the next scrape may have more luck (a timeout,
    a busy server); such an item is not remembered and is simply tried again."""

    def __init__(self, reason: str, *, lasting: bool = True):
        super().__init__(reason)
        self.lasting = lasting


def _lasting(error: ScrapeError) -> bool:
    if isinstance(error, FetchError):
        return error.status in CLOSED or (error.refused and error.status not in (429, 503))
    return True  # the page was downloaded and there was nothing to read on it


# --- previews (wizard, recipe editor, Claude's test tools) ------------------------

def preview_feed(feed: FeedRecipe, ctx: Context | None = None, *, pages: int = 1, limit: int = 8) -> dict:
    """List the first page(s) of a feed without storing anything."""
    ctx = ctx or Context()
    connector = connectors.get(feed.connector)
    listed: list[Item] = []
    page_reports: list[dict] = []
    for index, page in enumerate(connector.iter_pages(feed, ctx)):
        listed.extend(page.items)
        page_reports.append({"page": index + 1, "url": page.url, "items": len(page.items), **page.diagnostics})
        if index + 1 >= pages:
            break
    samples = listed[:limit]
    if len(page_reports) > 1 and len(listed) > limit:
        # show the tail too, so pagination can be judged
        samples = listed[: limit - 2] + listed[-2:]
    return {
        "feed": feed.name,
        "connector": feed.connector,
        "total_items": len(listed),
        "pages": page_reports,
        "items": [item.preview() for item in samples],
    }


def preview_article(url: str, rules: dict[str, str], ctx: Context | None = None, fetcher: str = "http") -> dict:
    """Extract one item page without storing anything."""
    ctx = ctx or Context()
    result = ctx.fetch(url, fetcher)
    extractor = pick(result)
    extracted = extractor.extract(result, rules, ctx)
    return {
        "url": result.url,
        "extractor": extractor.name,
        "title": extracted.title,
        "author": extracted.author,
        "published": extracted.published,
        "image_url": extracted.image_url,
        "pdf_url": extracted.pdf_url,
        "language": extracted.language,
        "summary": truncate(extracted.summary, 300),
        "text_characters": len(extracted.text),
        "text_start": truncate(extracted.text, 700),
        "text_end": extracted.text[-300:] if len(extracted.text) > 1000 else "",
    }


# --- scraping ---------------------------------------------------------------------

def build_article(feed: FeedRecipe, item: Item, recipe: Recipe, connector: Connector, ctx: Context, *,
                  skip_walled: bool = False) -> dict:
    """Combine what the listing said about an item with what its own page says.

    `skip_walled` is the source's choice for items whose own page cannot be read in full: raise `LeftOut`
    instead of keeping the lines that could be read."""
    listed_text = html_to_text(item.content_html) or item.summary
    partial_reason = wall = ""
    if connector.opens_items(feed):
        try:
            extracted = connector.read_item(item, feed, ctx)
            if extracted is None:
                result = ctx.fetch(item.url, feed.fetcher)
                extracted = pick(result).extract(result, recipe.article, ctx)
        except ScrapeError as error:
            if skip_walled:
                raise LeftOut(str(error), lasting=_lasting(error)) from error
            # The item page is blocked or unreadable. What the listing said is still worth keeping.
            if not (item.title and listed_text):
                raise
            extracted = Extracted(text=listed_text)
            partial_reason = str(error)
        else:
            wall = extracted.wall  # the page was read, but only as far as its login or paywall
            if wall and skip_walled:
                raise LeftOut(wall)
    else:
        extracted = Extracted(text=listed_text)
    teaser_only = bool(partial_reason or wall) or not (
        feed.fetch_detail or connector.inline_content or item.content_html)

    title = item.title if len(item.title) >= 12 else (extracted.title or item.title)
    text = extracted.text or title
    if not title:
        raise ExtractError(f"No title found for {item.url}")
    summary = item.summary or extracted.summary
    if len(summary) < 40 or summary == title:  # no teaser, or a "description" that is just the site's name
        summary = truncate(text.replace("\n", " "), 320) if text != title else ""
    tags = list(dict.fromkeys(tag for tag in [*item.tags, *extracted.tags] if tag))
    return {
        "video_id": item.extra.get("video_id", ""),  # a video: what its connector noted about it
        "views": int(item.extra.get("views") or 0),
        "duration_seconds": int(item.extra.get("duration") or 0),
        "audio_url": item.extra.get("audio_url", ""),  # a podcast episode: the audio file its feed offers
        "transcript": item.extra.get("transcript", ""),  # ... and the publisher's own transcript, if the feed has one
        "url": item.url,
        "title": title,
        "author": item.author or extracted.author,
        "published_at": better_date(item.published, extracted.published),
        "summary": truncate(summary, 600),
        "text": text,
        "image_url": extracted.image_url or item.image_url,
        "pdf_url": extracted.pdf_url,
        # the feed's declared type stands; an extractor only refines the generic ones (a PDF found in a news feed)
        "content_type": (extracted.content_type if extracted.content_type and feed.content_type in GENERIC_TYPES
                         else feed.content_type),
        "language": _language(extracted.language or recipe.language[:2].lower(), title, summary, text),
        "tags": ", ".join(tags[:20]),
        "word_count": word_count(text),
        "is_partial": teaser_only,
        "partial_reason": partial_reason,
        "wall": wall,
    }


def _language(said: str, title: str, summary: str, text: str) -> str:
    """The language an item is written in. A page's own label is taken, unless the text is plainly English:
    PISM labels its English publications "pl", an English Korean newspaper says "ko"."""
    if said in ("", "en"):
        return said
    from .translate import is_english

    return "en" if is_english(f"{title}\n{summary}\n{text[:3000]}") else said


def store_article(source_id: int, feed_name: str, article: dict) -> int | None:
    """Insert an article; returns its id, or None when the URL was already stored, or when you removed the
    item from the library (backend/removed.py): nothing stores that again."""
    if removed.among([article["url"]]):
        return None
    now = db.now()  # one moment for both: a transcript that came with the item is the publisher's own
    cursor = db.execute(
        """INSERT INTO articles(source_id, feed_name, url, title, author, published_at, fetched_at, summary, text,
                                image_url, pdf_url, content_type, language, tags, word_count, is_partial,
                                video_id, views, duration_seconds, audio_url, transcript, transcribed_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url) DO NOTHING""",
        (source_id, feed_name, article["url"], article["title"], article["author"], article["published_at"],
         now, article["summary"], article["text"], article["image_url"], article["pdf_url"],
         article["content_type"], article["language"], article["tags"], article["word_count"],
         int(article["is_partial"]), article.get("video_id", ""), article.get("views", 0),
         article.get("duration_seconds", 0), article.get("audio_url", ""), article.get("transcript", ""),
         now if article.get("transcript") else ""),
    )
    return cursor.lastrowid if cursor.rowcount else None


def known_urls(urls: list[str], left_out_by: int | None = None) -> set[str]:
    """Which of these addresses need not be opened: they are stored already or, when a source id is given,
    that source left them out before."""
    known: set[str] = set()
    for start in range(0, len(urls), 400):
        chunk = urls[start:start + 400]
        marks = ",".join("?" * len(chunk))
        known.update(r["url"] for r in db.rows(f"SELECT url FROM articles WHERE url IN ({marks})", chunk))
        if left_out_by is not None:
            known.update(r["url"] for r in db.rows(
                f"SELECT url FROM left_out WHERE source_id = ? AND url IN ({marks})", [left_out_by, *chunk]))
    return known


def remember_left_out(source_id: int, url: str, title: str, reason: str) -> None:
    db.execute(
        "INSERT INTO left_out(source_id, url, title, reason, at) VALUES(?,?,?,?,?)"
        " ON CONFLICT(source_id, url) DO UPDATE SET reason = excluded.reason, at = excluded.at",
        (source_id, url, title, truncate(reason, 300), db.now()))


def scrape_source(source_id: int, job: Job, *, deep: bool = False, limit: int = 0,
                  ctx: Context | None = None) -> dict:
    """Scrape every enabled feed of a source. `deep` walks the archive instead of stopping at known items.
    `limit` (with `deep`) says how far: the walk ends when that many new items are stored. What is stored
    already is passed without being opened, so asking again later goes on where the last time stopped."""
    ctx = ctx or Context()
    source = db.row("SELECT * FROM sources WHERE id = ?", (source_id,))
    if source is None:
        raise JobError("This source no longer exists.")
    recipe = Recipe.model_validate_json(source["recipe"])
    feeds = [feed for feed in recipe.feeds if feed.enabled]
    if not feeds:
        raise JobError("This source has no enabled feeds. Edit its recipe on the Structure tab.")

    first_time = not source["last_scraped_at"]
    max_pages = int(config.get("max_pages_deep" if deep else "max_pages_first" if first_time else "max_pages_update"))
    enrich, usage = _claude_switches(source, job)

    totals = {"new": 0, "failed": 0, "left_out": 0, "feeds": []}
    stored: list[int] = []  # ids of the items this run added
    errors: list[str] = []
    items = f"{limit:,} item{'' if limit == 1 else 's'}"
    if limit and deep:
        job.log(f"Going back through the archive until {limit:,} more item{'' if limit == 1 else 's'} "
                f"{'is' if limit == 1 else 'are'} stored. "
                f"What is stored already is passed without being opened.")
    elif limit:
        job.log(f"Collecting at most {items}, the newest first.")
    for feed in feeds:
        job.check_cancelled()
        if limit and totals["new"] >= limit:
            break  # the number asked for came out of the feeds before this one
        report = {"feed": feed.name, "new": 0, "failed": 0, "partial": 0, "left_out": 0, "pages": 0, "error": ""}
        try:
            _scrape_feed(source_id, feed, recipe, job, ctx, report, deep=deep, max_pages=max_pages,
                         totals=totals, stored=stored, skip_walled=bool(source["skip_walled"]), limit=limit)
        except ScrapeError as error:
            report["error"] = str(error)
            errors.append(f"{feed.name}: {error}")
            job.log(f"{feed.name}: {error}", "error")
        totals["feeds"].append(report)

    last_error = "; ".join(errors)
    db.execute("UPDATE sources SET last_scraped_at = ?, last_error = ? WHERE id = ?",
               (db.now(), last_error, source_id))
    job.log(f"Done: {totals['new']} new, {totals['failed']} skipped"
            + (f", {totals['left_out']} left out because their own page cannot be read." if totals["left_out"] else "."))
    if limit:
        totals["limit"], totals["reached"] = limit, totals["new"] >= limit
        if not deep and first_time:
            job.log(f"That is the {items} asked for; a deep scrape goes further back." if totals["reached"] else
                    f"The listing had fewer than the {items} asked for.")
        elif deep:
            job.log(f"That is the {limit:,} asked for; the archive goes on from here." if totals["reached"] else
                    f"The archive ran out before the {limit:,} asked for: there is nothing older to collect.")
    _after_storing(source_id, source, stored, job, totals, enrich, usage)
    if errors and len(errors) == len(feeds) and not totals["new"]:
        raise JobError(last_error)
    return totals


def _claude_switches(source: dict, job: Job) -> tuple[bool, object]:
    """Whether this source's items are labelled, and the tally Claude's cost is counted on (None when Claude
    is not used). A scrape translates only where the source's switch says so (`_translate_new`)."""
    enrich = bool(source["enrich_enabled"])
    usage = None
    if enrich:
        from ..ai import client as ai

        if ai.available():
            usage = ai.Usage()
        else:
            enrich = False
            job.log("AI summary + tags is on for this source, but there is no API key - skipping it.", "warn")
    return enrich, usage


def _after_storing(source_id: int, source: dict, stored: list[int], job: Job, totals: dict, enrich: bool,
                   usage) -> None:
    """What happens to items once they are stored. Claude's steps come after the scraping, not between the
    items: everything that was found is there to read at once, and stopping the run during them loses nothing
    that was scraped."""
    if source["write_videos"] and db.scalar(
            "SELECT 1 FROM articles WHERE source_id = ? AND (video_id != '' OR content_type = 'podcast')"
            " AND written_at = '' LIMIT 1", (source_id,)):
        from .videos import process

        totals["videos"], usage = process(source_id, job, usage, first=stored)
    if stored and source["translate_new"]:
        usage = _translate_new(stored, job, totals, usage)
    if stored and enrich:
        from .enrich import enrich_articles

        totals["labels"] = enrich_articles(stored, job, usage)
    if stored or totals.get("videos"):
        usage = _understand(job, totals, usage)
    if usage is not None:
        job.usage = usage.as_dict()


def _translate_new(stored: list[int], job: Job, totals: dict, usage):
    """The source's switch *Translate new items to English*: the new items in another language, the shortest
    first, as long as they are no longer than the reading time in Settings, and within what one run may spend
    (together with the other Claude steps of the run). What is left, the source's Translate button does."""
    from ..ai import client as ai
    from . import translate

    ids, too_long = translate.among_new(stored)
    if not ids and not too_long:
        return usage
    if not ai.available():
        job.log("Translate new items is on for this source, but there is no API key - skipping it.", "warn")
        return usage
    minutes = config.get("translate_max_minutes")
    job.log(f"Translating {len(ids)} new item{'' if len(ids) == 1 else 's'} that {'is' if len(ids) == 1 else 'are'}"
            f" not in English ({config.model_label(str(config.get('model_translate')))})."
            + (f" {too_long} longer than a {minutes}-minute read {'is' if too_long == 1 else 'are'} left as "
               f"{'it is' if too_long == 1 else 'they are'}; the reader translates one of them." if too_long else ""))
    usage = usage if usage is not None else ai.Usage()
    totals["translation"] = {**translate.translate_articles(ids, job, usage), "too_long": too_long}
    return usage


# --- one page or one video, saved by its address -------------------------------------------

SAVED = {
    "article": ("Saved articles", "Single pages you saved by their address."),
    "video": ("Saved videos", "Single YouTube videos you saved by their address."),
    "podcast": ("Saved podcasts", "Single podcast episodes you saved by their Spotify address."),
}
# For a saved item of each kind: the connector that reads it, and where its source says it comes from.
SAVED_FROM = {"article": ("single", ""), "video": ("youtube", "https://www.youtube.com/"),
              "podcast": ("podcast", "https://open.spotify.com/")}


def saved_source(kind: str) -> int:
    """The source that single saved items of this kind ('article', 'video', 'podcast') belong to; made on first use.
    It has no feeds, so there is nothing to update: items only arrive when you save one."""
    found = db.row("SELECT id FROM sources WHERE analyzer = ?", (f"saved-{kind}",))
    if found:
        return found["id"]
    name, description = SAVED[kind]
    recipe = Recipe(site_name=name, description=description, structure_report=(
        f"**{name}** is where items go that you saved one at a time with *Save one page or video*. It has no "
        f"listing to scrape; its switches on the Settings tab apply to whatever you save next."))
    return db.execute(
        "INSERT INTO sources(name, url, description, icon_url, recipe, analyzer, created_at) VALUES(?,?,?,?,?,?,?)",
        (name, SAVED_FROM[kind][1], description,
         f"{SAVED_FROM[kind][1]}favicon.ico" if SAVED_FROM[kind][1] else "", recipe.model_dump_json(),
         f"saved-{kind}", db.now())).lastrowid


def save_link(url: str, kind: str, job: Job, ctx: Context | None = None) -> dict:
    """Store one page, one YouTube video or one podcast episode, then treat it like any scraped item: write a
    video or an episode up, label, embed, as its saved source is set to."""
    ctx = ctx or Context()
    # The source the item goes to is only made once there is an item: a failed save leaves nothing behind.
    existing = db.row("SELECT * FROM sources WHERE analyzer = ?", (f"saved-{kind}",))
    recipe = Recipe.model_validate_json(existing["recipe"]) if existing else Recipe(site_name=SAVED[kind][0])
    video = kind == "video"
    feed = FeedRecipe(name="Saved", connector=SAVED_FROM[kind][0], url=url, content_type=kind)
    connector = connectors.get(feed.connector)
    job.log(f"Opening {url}")
    try:
        items = next(iter(connector.iter_pages(feed, ctx))).items
        if not items:
            raise ScrapeError("YouTube knows no video at this address (it may be private, removed, or a stream "
                              "that has not ended)." if video else "There is nothing to read at this address.")
        article = build_article(feed, items[0], recipe, connector, ctx,
                                skip_walled=bool(existing and existing["skip_walled"]))
        if items[0].extra.get("no_audio"):  # a podcast episode that can be stored but not listened to
            job.log(items[0].extra["no_audio"], "warn")
    except LeftOut as out:
        raise JobError(f"Not saved, because the page cannot be read ({out}) and {SAVED[kind][0]} is set to leave "
                       f"such items out.") from out
    except ScrapeError as error:
        raise JobError(f"This could not be saved: {error}") from error
    source_id = saved_source(kind)
    source = db.row("SELECT * FROM sources WHERE id = ?", (source_id,))
    article_id = store_article(source_id, feed.name, article)
    stored = [article_id] if article_id else []
    if article_id is None:  # someone was quicker: it is in the library already
        article_id = db.scalar("SELECT id FROM articles WHERE url = ?", (article["url"],))
        if article_id is None:
            raise JobError("Not saved: you removed this item from your library. Put it back from the list of "
                           "removed items.")
    db.execute("UPDATE sources SET last_scraped_at = ? WHERE id = ?", (db.now(), source_id))
    job.log(f"Saved: {article['title']}" + (f" (only partly: {article['wall'] or article['partial_reason']})"
                                           if article["wall"] or article["partial_reason"] else ""))
    totals = {"new": len(stored), "failed": 0, "left_out": 0, "feeds": [], "article_id": article_id,
              "partial": bool(article["is_partial"]), "wall": article["wall"]}
    enrich, usage = _claude_switches(source, job)
    _after_storing(source_id, source, stored, job, totals, enrich, usage)
    return totals


def _understand(job: Job, totals: dict, usage):
    """The last step of a scrape: embed what is new (free, on this computer), then let the topics that keep
    themselves up to date write their "What is new". Neither may fail the scrape: what was scraped is stored."""
    from ..search import embed

    if not embed.missing():
        try:
            totals["embedded"] = embed.embed_pending(job)["embedded"]
        except embed.Unavailable as error:
            job.log(str(error), "warn")
    from .. import addons

    found = addons.after_scrape(job)  # free steps of the add-ons, such as watching foresight signposts
    if found:
        totals["addons"] = found
    from ..ai import briefing
    from ..ai import client as ai

    if ai.available() and db.scalar("SELECT 1 FROM topics WHERE auto_update = 1"):
        usage = usage if usage is not None else ai.Usage()
        totals["topics"] = briefing.update_topics(job, usage)
    return usage


def _scrape_feed(source_id: int, feed: FeedRecipe, recipe: Recipe, job: Job, ctx: Context, report: dict, *,
                 deep: bool, max_pages: int, totals: dict, stored: list[int], skip_walled: bool = False,
                 limit: int = 0) -> None:
    connector = connectors.get(feed.connector)
    max_pages = connector.page_limit(feed, deep) or max_pages
    if limit:
        max_pages = max(max_pages, PAGES_FOR_A_NUMBER)
    unread: set[str] = set()  # sites whose item pages could not be read
    for page_index, page in enumerate(connector.iter_pages(feed, ctx)):
        job.check_cancelled()
        report["pages"] = page_index + 1
        if not page.items:
            if page_index == 0:
                reason = page.diagnostics.get("note") or ("the listing returned no items - the site may have "
                                                          "changed; re-analyse the source if this keeps happening.")
                job.log(f"{feed.name}: {reason}", "warn")
            break
        urls = [item.url for item in page.items]
        gone = removed.among(urls)  # what you removed yourself counts as known: it is not opened or stored again
        known = known_urls(urls, source_id if skip_walled else None) | gone
        fresh = [item for item in page.items if item.url not in known]
        # A newest-first listing (a channel, a podcast): an update ends at the first item that is stored already,
        # and leaves what comes after it alone, also when that was never stored (left out on purpose).
        reached_stored = older = 0
        if connector.newest_first and not deep:
            first_known = next((index for index, item in enumerate(page.items) if item.url in known), None)
            if first_known is not None:
                reached_stored = True
                older = sum(1 for item in page.items[first_known:] if item.url not in known)
                fresh = [item for item in page.items[:first_known] if item.url not in known]
        for item in page.items:  # a video that is stored already: its number of views has moved on
            if item.url in known and item.extra.get("views"):
                db.execute("UPDATE articles SET views = ? WHERE url = ? AND video_id != ''",
                           (int(item.extra["views"]), item.url))
        job.log(f"{feed.name} · page {page_index + 1}: {len(page.items)} items, {len(fresh)} new"
                + (f", {len(gone)} that you removed and that stay out" if gone else "")
                + (f", {older} older than what is stored, which an update leaves to a deep scrape" if older else ""))
        for item in fresh:
            job.check_cancelled()
            try:
                article = build_article(feed, item, recipe, connector, ctx, skip_walled=skip_walled)
                article_id = store_article(source_id, feed.name, article)
            except LeftOut as out:
                report["left_out"] += 1
                totals["left_out"] += 1
                if out.lasting:
                    remember_left_out(source_id, item.url, item.title, str(out))
                site = host_of(item.url)
                if site not in unread:  # say why once per site, not once per item
                    unread.add(site)
                    job.log(f"{feed.name}: items of {site} are left out, because their own page cannot be read "
                            f"({out})" + ("" if out.lasting else "; they are tried again at the next scrape"), "warn")
                continue
            except ScrapeError as error:
                report["failed"] += 1
                totals["failed"] += 1
                job.log(f"Skipped {item.url} - {error}", "warn")
                continue
            if article_id is None:
                continue
            report["new"] += 1
            totals["new"] += 1
            if article["partial_reason"] or article["wall"]:
                report["partial"] += 1
                site = host_of(article["url"])
                if site not in unread:  # say why once per site, not once per item
                    unread.add(site)
                    if article["wall"]:
                        job.log(f"{feed.name}: items of {site} are behind a login or paywall ({article['wall']}). "
                                f"What could be read is stored and marked as partial; to leave such items out, "
                                f"switch that on on the source's Settings tab.", "warn")
                    else:
                        job.log(f"{feed.name}: pages of {site} cannot be read, so what the listing said is stored "
                                f"instead ({article['partial_reason']})", "warn")
            stored.append(article_id)
            job.progress(totals["new"], limit or None, f"{feed.name}: {truncate(article['title'], 70)}")
            if limit and totals["new"] >= limit:
                return  # as far back as was asked for
        if not deep and (not fresh or reached_stored):
            break  # caught up with what we already have
        if page_index + 1 >= max_pages:
            break
