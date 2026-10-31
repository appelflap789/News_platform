"""Site scrapers: the plugin slot (driven by a scraper for the fake site) and the Clingendael scraper
(driven by pages saved from the real site, so no internet is needed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config, db
from backend.analyzers.claude_agent import feed_schema, system_prompt
from backend.connectors import Context
from backend.extractors import ExtractError
from backend.extractors.pdf_document import pdf_text
from backend.fetchers import FetchError, FetchResult
from backend.jobs import JobError
from backend.main import app
from backend.pipeline.scrape import preview_feed, scrape_source
from backend.schemas import FeedRecipe, Recipe, validate_recipe
from backend.scrapers import SiteScraper, Stream, csis, scrapers
from backend.scrapers._sources import recipe_for
from backend.scrapers.base import Extracted, Item, ListPage
from backend.scrapers.clingendael import LISTING
from backend.util import canonical_url, clean, element_text, parse_date
from tests.conftest import PDF
from tests.test_api import wait_for
from tests.test_pipeline import add_source

FIXTURES = Path(__file__).parent / "fixtures"


@scrapers.register
class ExampleInstitute(SiteScraper):
    """A scraper for the fake site of the test suite, written the way a real one is."""

    name = "example"
    label = "Example Institute"
    homepage = "http://example.invalid"
    description = "The fake site of the test suite."
    language = "en"
    notes = "Listing at `/publications`, two cards a page."
    streams = [Stream("publications", "Publications", "http://example.invalid/publications")]
    archive_pages = 10
    unreadable: set[str] = set()  # slugs on which read_item trips, as code does when a page is laid out differently

    def list_pages(self, stream, ctx):
        number = 0
        while True:
            page = self.open(f"{stream.url}?page={number}", ctx)
            cards = page.soup.select("article.teaser")
            if not cards:
                return
            yield ListPage([
                Item(url=canonical_url(page.link(card.select_one("a")["href"])),
                     title=clean(card.select_one("h3").get_text()),
                     published=parse_date(card.select_one("time")["datetime"]))
                for card in cards
            ], page.url)
            number += 1

    def read_item(self, item, stream, ctx):
        page = self.open(item.url, ctx)
        if item.url.rsplit("/", 1)[-1] in self.unreadable:
            page.soup.select_one("div.no-such-thing").get_text()
        body = page.soup.select_one("div.body")
        download = body.select_one("a.download")
        pdf_url = page.link(download["href"]) if download else ""
        if download:
            download.decompose()
        report = self.pdf_text(pdf_url, ctx) if pdf_url else ""
        return Extracted(
            author=clean(page.soup.select_one(".byline").get_text()),
            text="\n\n".join(part for part in (element_text(body), report) if part),
            pdf_url=pdf_url,
            content_type="report" if pdf_url else "",
            tags=["built"],
        )


@scrapers.register
class ExamplePlain(ExampleInstitute):
    """Lists the same way, but leaves reading the items to the platform's extractors."""

    name = "example_plain"

    def read_item(self, item, stream, ctx):
        return None


def scraper_feed(site: str, scraper: str = "example", **extra) -> FeedRecipe:
    return FeedRecipe(name="Publications", connector="scraper", url=f"{site}/publications",
                      options={"scraper": scraper, "stream": "publications"}, **extra)


def scraper_source(site: str, scraper: str = "example") -> int:
    return add_source(Recipe(site_name="Example Institute", homepage=site, language="en",
                             feeds=[scraper_feed(site, scraper)]))


@pytest.fixture(autouse=True)
def readable():
    ExampleInstitute.unreadable = set()
    yield


# --- the slot ----------------------------------------------------------------------------

def test_a_site_scraper_runs_as_a_feed(site, job):
    totals = scrape_source(scraper_source(site), job)
    assert totals["new"] == 6 and totals["failed"] == 0
    assert totals["feeds"][0]["pages"] == 3  # the listing ran out by itself
    stored = db.row("SELECT * FROM articles WHERE url = ?", (f"{site}/publications/p1",))
    assert stored["title"] == "Drone swarms and the future of air defence"  # from the listing
    assert stored["published_at"] == "2026-09-28T00:00:00Z"
    assert stored["author"] == "Jane Researcher"  # from read_item
    assert stored["pdf_url"] == f"{site}/files/p1.pdf"
    assert "Autonomous drone swarms" in stored["text"] and "Line 12 of the full report" in stored["text"]
    assert "Download the report" not in stored["text"]
    assert stored["content_type"] == "report" and stored["tags"] == "built" and not stored["is_partial"]
    plain = db.row("SELECT * FROM articles WHERE url = ?", (f"{site}/publications/p2",))
    assert plain["content_type"] == "article" and plain["pdf_url"] == ""


def test_a_scraper_can_leave_the_reading_to_the_extractors(site, job):
    assert scrape_source(scraper_source(site, "example_plain"), job)["new"] == 6
    stored = db.row("SELECT * FROM articles WHERE url = ?", (f"{site}/publications/p3",))
    assert "Anduril builds autonomous systems" in stored["text"]
    assert stored["image_url"] == f"{site}/img/p3-large.jpg"  # found by the html extractor, not by the scraper


def test_the_scraper_decides_how_deep_a_deep_scrape_goes(site, job):
    config.update({"max_pages_first": 1, "max_pages_deep": 1})
    source_id = scraper_source(site)
    assert scrape_source(source_id, job)["new"] == 2  # an ordinary scrape follows the Settings page
    assert scrape_source(source_id, job, deep=True)["new"] == 4  # a deep one follows `archive_pages`


def test_a_page_the_scraper_trips_on_costs_one_item(site, job):
    ExampleInstitute.unreadable = {"p4"}
    totals = scrape_source(scraper_source(site), job)
    assert totals["new"] == 5 and totals["failed"] == 1
    assert "could not read this page (AttributeError" in job.text()


def test_a_listing_the_scraper_trips_on_is_reported_as_the_feeds_error(site, job, monkeypatch):
    def broken(self, stream, ctx):
        raise KeyError("href")
        yield  # pragma: no cover - makes this a generator, like the real method

    monkeypatch.setattr(ExampleInstitute, "list_pages", broken)
    with pytest.raises(JobError, match="scraper 'example' failed while listing"):
        scrape_source(scraper_source(site), job)


def test_a_site_repeating_its_last_page_does_not_loop_forever(site, monkeypatch):
    def endless(self, stream, ctx):
        while True:
            yield ListPage([Item(url=f"{stream.url}/p1", title="Drone swarms and the future of air defence")],
                           stream.url)

    monkeypatch.setattr(ExampleInstitute, "list_pages", endless)
    preview = preview_feed(scraper_feed(site), pages=50)
    assert [page["items"] for page in preview["pages"]] == [1, 0]


def test_a_missing_scraper_is_named(site, job):
    with pytest.raises(JobError, match="no scraper called 'gone'"):
        scrape_source(scraper_source(site, "gone"), job)


def test_the_feed_address_overrides_the_one_in_the_code(site):
    assert ExampleInstitute.streams[0].url.startswith("http://example.invalid")
    assert preview_feed(scraper_feed(site))["total_items"] == 2


def test_claude_is_not_offered_the_scraper_connector(site):
    assert "scraper" not in feed_schema()["properties"]["connector"]["enum"]
    assert "backend/scrapers" not in system_prompt()
    validate_recipe(Recipe(site_name="X", feeds=[scraper_feed(site)]))  # but a recipe may use it


def test_recipe_for_a_scraper():
    recipe = recipe_for(scrapers.get("example"))
    validate_recipe(recipe)
    assert recipe.site_name == "Example Institute" and recipe.icon_url == "http://example.invalid/favicon.ico"
    assert recipe.structure_report.startswith("Listing at")
    feed = recipe.feeds[0]
    assert (feed.connector, feed.options) == ("scraper", {"scraper": "example", "stream": "publications"})


def test_scrapers_are_added_from_the_dashboard(site, monkeypatch):
    monkeypatch.setattr(ExampleInstitute, "streams", [Stream("publications", "Publications", f"{site}/publications")])
    with TestClient(app) as api:
        listed = {entry["name"]: entry for entry in api.get("/api/scrapers").json()}
        assert {"clingendael", "example"} <= set(listed)
        assert listed["example"]["source_id"] is None and listed["example"]["label"] == "Example Institute"

        added = api.post("/api/scrapers/example/add", json={}).json()
        assert wait_for(api, added["job_id"])["result"]["new"] == 6
        source = api.get(f"/api/sources/{added['id']}").json()
        assert source["name"] == "Example Institute" and source["article_count"] == 6
        assert source["recipe"]["feeds"][0]["connector"] == "scraper"
        assert {e["name"]: e["source_id"] for e in api.get("/api/scrapers").json()}["example"] == added["id"]

        assert api.post("/api/scrapers/example/add", json={}).status_code == 409
        assert api.post("/api/scrapers/nope/add", json={}).status_code == 404
        connector = next(c for c in api.get("/api/meta").json()["connectors"] if c["name"] == "scraper")
        assert [field["key"] for field in connector["fields"]] == ["scraper", "stream"]


# --- Clingendael, against pages saved from the real site ------------------------------------

REPORT = "https://www.clingendael.org/publication/effects-hybrid-conflict-escalation-management"
HERO = ("https://www.clingendael.org/publication/"
        "european-business-survey-bridging-gap-between-geopolitics-and-corporate-strategy")
ARTICLE = "https://www.clingendael.org/publication/ethiopias-widening-war-threatens-horn-africa"
SAVED = {
    LISTING: "listing_first.html",
    f"{LISTING}?page=1": "listing_last.html",
    f"{LISTING}?page=2": "listing_past_end.html",
    REPORT: "report.html",
    HERO: "report_hero_layout.html",
    ARTICLE: "article.html",
}


class SavedSite(Context):
    """Serves the saved pages; every PDF is the small test PDF."""

    def fetch(self, url: str, fetcher: str = "http", **kwargs) -> FetchResult:
        if url.lower().endswith(".pdf"):
            return FetchResult(url, 200, "application/pdf", PDF)
        if url not in SAVED:
            raise FetchError(f"HTTP 404 for {url}")
        return FetchResult(url, 200, "text/html", (FIXTURES / "clingendael" / SAVED[url]).read_bytes(), "utf-8")


@pytest.fixture
def clingendael():
    scraper = scrapers.get("clingendael")
    return scraper, scraper.streams[0], SavedSite()


def test_clingendael_listing(clingendael):
    scraper, stream, ctx = clingendael
    pages = list(scraper.list_pages(stream, ctx))
    assert [len(page.items) for page in pages] == [11, 9]  # 12 cards on the first page, one of them a podcast
    first = pages[0].items[0]
    assert first.url == REPORT and first.title == "Effects of hybrid conflict on escalation management"
    assert first.author == "Sico van der Meer, Karen van Loon" and first.tags == ["Reports and papers"]
    assert first.image_url.startswith("https://www.clingendael.org/sites/default/files/")
    listed = [item for page in pages for item in page.items]
    assert not any("podcast" in item.url for item in listed)
    assert {tag for item in listed for tag in item.tags} <= {"Reports and papers", "Policy briefs", "Articles",
                                                             "Op-ed", "Alerts"}


def test_clingendael_report_reads_the_pdf_behind_the_button(clingendael):
    scraper, stream, ctx = clingendael
    read = scraper.read_item(Item(url=REPORT, tags=["Reports and papers"]), stream, ctx)
    assert read.published == "2026-10-09T00:00:00Z" and read.content_type == "report" and read.language == "en"
    assert read.author == "Sico van der Meer, Karen van Loon"  # not the authors of the related publications
    assert read.pdf_url.endswith("/2026-10/Speed_attribution_and_nuclear_wormholes.pdf")
    assert read.summary.startswith("Contemporary conflict escalation can no longer be adequately understood")
    assert read.text.startswith("In short\n\nContemporary conflict escalation")
    assert "Escalation of international conflict often occurs suddenly." in read.text  # the abstract on the page
    assert "Line 12 of the full report" in read.text  # the PDF
    assert "Read Report" not in read.text and "Related" not in read.text
    assert read.image_url.startswith("https://www.clingendael.org/sites/default/files/styles/c_header_image/")


def test_clingendael_hero_layout(clingendael):
    scraper, stream, ctx = clingendael
    read = scraper.read_item(Item(url=HERO, tags=["Reports and papers"], image_url="thumb.jpg"), stream, ctx)
    assert read.published == "2026-09-14T00:00:00Z" and read.author == "Maaike Heijmans"
    assert read.image_url == ""  # the listing's thumbnail stands
    assert read.pdf_url.endswith("/2026-09/Clingendael_report_European_Business_Survey.pdf")
    assert read.content_type == "report" and "Six findings stand out" in read.text


def test_clingendael_article_has_its_text_on_the_page(clingendael):
    scraper, stream, ctx = clingendael
    read = scraper.read_item(Item(url=ARTICLE, tags=["Articles"]), stream, ctx)
    assert read.published == "2026-10-02T00:00:00Z" and read.author == "Jos Meester"
    assert read.pdf_url == "" and read.content_type == "article"
    assert len(read.text) > 10_000 and "What should be done?" in read.text
    assert read.summary.startswith("Renewed war in Tigray")


# --- CSIS, against pages and a sitemap saved from the real site ---------------------------------

CSIS_REPORT = "https://www.csis.org/analysis/russias-turn-china-under-sanctions"
CSIS_COMMENTARY = "https://www.csis.org/analysis/learning-without-bleeding-chinas-lessons-russia-ukraine-drone-war"
CSIS_OLDEST = "https://www.csis.org/analysis/turkey-update-clinton-turkey-reviewing"
CSIS_SAVED = {
    csis.LISTING: "listing.html",
    csis.SITEMAP: "sitemap.xml",
    f"{csis.SITEMAP}?page=1": "sitemap_1.xml",
    f"{csis.SITEMAP}?page=2": "sitemap_2.xml",
    f"{csis.SITEMAP}?page=3": "sitemap_3.xml",
    CSIS_REPORT: "report.html",
    CSIS_COMMENTARY: "commentary.html",
    CSIS_OLDEST: "newsletter_1999.html",
}


class SavedCsis(Context):
    """Serves what was saved from csis.org; every PDF is the small test PDF. The listing's further pages are
    answered the way the real site answers a scraper: with a bot challenge. `closed` makes it refuse every item."""

    def __init__(self, closed: bool = False) -> None:
        self.closed = closed
        self.asked: list[str] = []

    def fetch(self, url: str, fetcher: str = "http", **kwargs) -> FetchResult:
        self.asked.append(url)
        if ".pdf" in url.lower():
            return FetchResult(url, 200, "application/pdf", PDF)
        if url.startswith(f"{csis.LISTING}?") or (self.closed and url.startswith(csis.ITEMS)):
            raise FetchError(f"www.csis.org answered with a Cloudflare bot challenge (HTTP 403 for {url})",
                             refused=True, status=403)
        if url not in CSIS_SAVED:
            raise FetchError(f"HTTP 404 for {url}", status=404)
        kind = "application/xml" if url.split("?")[0].endswith(".xml") else "text/html"
        return FetchResult(url, 200, kind, (FIXTURES / "csis" / CSIS_SAVED[url]).read_bytes(), "utf-8")


@pytest.fixture
def csis_site():
    scraper = csis.Csis()  # a scraper of its own: the shared one remembers the sitemap for hours
    return scraper, {stream.key: stream for stream in scraper.streams}, SavedCsis()


def test_csis_latest_is_the_first_page_with_every_kind_of_item(csis_site):
    scraper, streams, ctx = csis_site
    pages = list(scraper.list_pages(streams["latest"], ctx))
    assert [len(page.items) for page in pages] == [10]  # reports and commentaries have cards of different classes
    assert ctx.asked == [csis.LISTING]  # and no ?page=1: that is behind the bot challenge
    first, three_authors, transcript = pages[0].items[0], pages[0].items[1], pages[0].items[5]
    assert first.url == CSIS_REPORT and first.title.startswith("Russia’s Turn to China Under Sanctions")
    assert first.author == "Damien Spleeters" and first.published == "2026-10-09T00:00:00Z"
    assert first.tags == ["Report"] and first.summary.startswith("Sanctions lose force")
    assert three_authors.author == "Lauren Mai, Andreyka Natalegawa, Gregory B. Poling, Japhet Quitzon"
    assert transcript.tags == ["Transcript"] and transcript.author == "" and transcript.published == "2026-10-07T00:00:00Z"
    assert [item.tags[0] for item in pages[0].items] == ["Report", "Report", "Report", "Report", "Commentary",
                                                         "Transcript", "Newsletter", "Newsletter", "Report", "Commentary"]


def test_csis_archive_walks_the_sitemap_from_the_newest_end_of_each_run(csis_site):
    scraper, streams, ctx = csis_site
    pages = list(scraper.list_pages(streams["archive"], ctx))
    listed = [item.url for page in pages for item in page.items]
    # 45 commentaries (with press releases in between), then blogs, a run of 6, events, and a run of 20 reports
    assert [len(page.items) for page in pages] == [30, 30, 11] and len(set(listed)) == 71
    assert all(url.startswith(csis.ITEMS) for url in listed)  # no events, blogs, programs, topics or press releases
    assert listed[:3] == [
        "https://www.csis.org/analysis/time-confront-escalating-russia-iran-intelligence-cooperation",  # commentary
        "https://www.csis.org/analysis/terrorism-threat-2026-midterm-elections-what-data-tells-us",  # report
        "https://www.csis.org/analysis/trump-administration-ratchets-export-control-penalties",  # the small run
    ]
    assert listed[-1] == CSIS_OLDEST  # from 1999
    # each run in its own order, newest first, and each at its own pace: after 30 of 71, about 42% of every run
    runs = csis.runs_of([loc for number in (1, 2, 3)
                         for loc in csis.LOC.findall((FIXTURES / "csis" / f"sitemap_{number}.xml").read_text("utf-8"))])
    assert [len(run) for run in runs] == [45, 6, 20]
    for run in runs:
        order = [url for url in listed if url in run]
        assert order == run[::-1]
        assert abs(len([url for url in listed[:30] if url in run]) - len(run) * 30 / 71) <= 1
    assert pages[0].diagnostics == {"addresses_in_sitemap": 71, "from": 1, "to": 30}

    assert len(ctx.asked) == 4  # the index and its three pages
    list(scraper.list_pages(streams["archive"], ctx))
    assert len(ctx.asked) == 4  # an update an hour later does not download the sitemap again


def test_csis_report_has_its_date_read_month_first(csis_site):
    scraper, streams, ctx = csis_site
    read = scraper.read_item(Item(url=CSIS_REPORT), streams["archive"], ctx)
    assert read.title.startswith("Russia’s Turn to China Under Sanctions: Sanctions Decay")  # the archive lists no titles
    assert read.published == "2026-10-09T00:00:00Z"  # the page says 10/09/2026, which is not 10 September
    assert read.author == "Damien Spleeters" and read.content_type == "report" and read.language == "en"
    assert read.tags == ["Report", "Economic Security and Technology",
                         "Economics Program and Scholl Chair in International Business"]
    assert read.summary.startswith("Sanctions lose force not only when governments stop updating them")
    assert len(read.text) > 20_000 and read.text.startswith("In May 2026, Ukraine’s sanctions commissioner")
    assert "Related Content" not in read.text and "Programs & Projects" not in read.text
    assert read.pdf_url == "" and read.image_url.startswith("https://csis-website-prod.s3.amazonaws.com/")
    assert ctx.asked == [CSIS_REPORT]  # the text is on the page: no PDF is fetched


def test_csis_commentary_joins_the_text_around_its_figures(csis_site):
    scraper, streams, ctx = csis_site
    read = scraper.read_item(Item(url=CSIS_COMMENTARY, tags=["Commentary"]), streams["latest"], ctx)
    assert read.author == "Lilly Min-Chen Lee, Kateryna Bondar" and read.published == "2026-10-07T00:00:00Z"
    assert read.content_type == "article" and read.tags[0] == "Commentary" and "Wadhwani AI Center" in read.tags
    for part in ("At a People’s Liberation Army (PLA) center", "The intervals show a consistent pattern.",
                 "China’s study of the drone war runs through distributed channels."):  # three blocks of text
        assert part in read.text
    assert read.text.index("The intervals show") < read.text.index("China’s study of the drone war")


def test_csis_piece_from_1999_is_read_from_its_pdf(csis_site):
    scraper, streams, ctx = csis_site
    read = scraper.read_item(Item(url=CSIS_OLDEST), streams["archive"], ctx)
    assert read.title == "Turkey Update: Clinton in Turkey: Reviewing" and read.published == "1999-11-16T00:00:00Z"
    assert read.tags == ["Newsletter", "Turkey Project"] and read.content_type == "article"
    assert read.pdf_url.endswith("/legacy_files/files/media/csis/pubs/tu991116.pdf")
    assert "Line 12 of the full report" in read.text  # the page itself has no text


def test_a_protected_pdf_costs_its_text_not_the_item(csis_site, monkeypatch):
    import pypdf
    from pypdf.errors import DependencyError

    def locked(self, *args, **kwargs):  # what pypdf does with an AES-encrypted file here
        raise DependencyError("cryptography>=3.1 is required for AES algorithm")

    monkeypatch.setattr(pypdf.PdfReader, "__init__", locked)
    with pytest.raises(ExtractError, match="protected"):
        pdf_text(PDF, "https://example.org/report.pdf")
    scraper, streams, ctx = csis_site
    read = scraper.read_item(Item(url=CSIS_OLDEST), streams["archive"], ctx)
    assert read.title == "Turkey Update: Clinton in Turkey: Reviewing" and read.text == ""
    assert read.pdf_url.endswith("tu991116.pdf")  # the reader's PDF button still leads to it


def test_csis_is_left_alone_when_it_keeps_refusing(csis_site):
    scraper, streams, _ = csis_site
    ctx = SavedCsis(closed=True)
    pages = scraper.list_pages(streams["archive"], ctx)
    first = next(pages)
    for item in first.items[:csis.STOP_AFTER]:
        with pytest.raises(FetchError, match="bot challenge"):
            scraper.read_item(item, streams["archive"], ctx)
    asked = len(ctx.asked)
    for item in first.items[csis.STOP_AFTER:]:
        with pytest.raises(FetchError, match="refused the scraper 5 times in a row"):
            scraper.read_item(item, streams["archive"], ctx)
    assert len(ctx.asked) == asked  # not one more request
    assert list(pages) == []  # and the rest of the archive is not walked

    # a page that is simply gone is not a refusal, and one that opens wipes the slate
    ctx = SavedCsis()
    for _ in range(3):
        ctx.closed = True
        with pytest.raises(FetchError):
            scraper.read_item(Item(url=CSIS_REPORT), streams["archive"], ctx)
        ctx.closed = False
        with pytest.raises(FetchError, match="404"):
            scraper.read_item(Item(url=f"{csis.ITEMS}no-such-piece"), streams["archive"], ctx)
        assert scraper.read_item(Item(url=CSIS_REPORT), streams["archive"], ctx).title


def test_csis_runs_as_a_source_with_two_feeds(job):
    config.update({"max_pages_first": 1})
    recipe = recipe_for(scrapers.get("csis"))
    assert [(feed.name, feed.opt("stream")) for feed in recipe.feeds] == [("Latest", "latest"), ("Archive", "archive")]
    source_id = add_source(recipe)
    scrapers.get("csis")._listed.clear()
    totals = scrape_source(source_id, job, ctx=SavedCsis())
    by_feed = {feed["feed"]: feed for feed in totals["feeds"]}
    # Latest: ten cards; the two saved pages are read in full, the other eight keep what their card said
    assert (by_feed["Latest"]["new"], by_feed["Latest"]["partial"], by_feed["Latest"]["pages"]) == (10, 8, 1)
    # Archive: a first scrape takes one page of 30 addresses; none of their pages was saved, and none is a card
    assert (by_feed["Archive"]["new"], by_feed["Archive"]["failed"], by_feed["Archive"]["pages"]) == (0, 30, 1)
    report = db.row("SELECT * FROM articles WHERE url = ?", (CSIS_REPORT,))
    assert report["content_type"] == "report" and report["published_at"] == "2026-10-09T00:00:00Z"
    assert report["word_count"] > 3000 and not report["is_partial"] and report["feed_name"] == "Latest"
    assert report["tags"].startswith("Report, Economic Security and Technology")
    assert report["image_url"].startswith("https://csis-website-prod.s3.amazonaws.com/s3fs-public/2026-10/")  # not the thumbnail
    teaser = db.row("SELECT * FROM articles WHERE url = ?", (f"{csis.ITEMS}ai-export-dilemma",))
    assert teaser["is_partial"] and teaser["title"] == "The AI Export Dilemma" and teaser["author"] == "William Alan Reinsch"
