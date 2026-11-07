"""Scraping a source end to end, searching what was stored, and the scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import config, db, scheduler
from backend.analyzers import analyzers
from backend.connectors import Context
from backend.fetchers import FetchError
from backend.jobs import JobError
from backend.pipeline.scrape import scrape_source
from backend.schemas import FeedRecipe, Recipe
from backend.search import query
from tests.conftest import Handler
from tests.test_plugins import listing_feed


def add_source(recipe: Recipe, **columns) -> int:
    values = {"name": recipe.site_name, "url": recipe.homepage or "https://example.org", "recipe":
              recipe.model_dump_json(), "created_at": db.now(), **columns}
    names = ", ".join(values)
    marks = ", ".join("?" * len(values))
    return db.execute(f"INSERT INTO sources({names}) VALUES({marks})", list(values.values())).lastrowid


def institute(site: str) -> Recipe:
    return Recipe(site_name="Example Institute", homepage=site, language="en", feeds=[
        listing_feed(site, pagination="next_link", next_selector="a.pager__next"),
        FeedRecipe(name="News", connector="rss", url=f"{site}/feed.xml", content_type="news"),
    ])


@pytest.fixture
def scraped(site, job) -> int:
    source_id = add_source(institute(site))
    scrape_source(source_id, job, deep=True)
    return source_id


def test_scrape_stores_articles_from_every_feed(site, job):
    source_id = add_source(institute(site))
    totals = scrape_source(source_id, job, deep=True)

    assert totals["new"] == 9 and totals["failed"] == 0
    assert {f["feed"]: f["new"] for f in totals["feeds"]} == {"Publications": 6, "News": 3}
    stored = db.rows("SELECT * FROM articles ORDER BY url")
    assert len(stored) == 9
    report = next(a for a in stored if a["url"].endswith("/publications/p1"))
    assert report["title"] == "Drone swarms and the future of air defence"
    assert report["content_type"] == "report" and report["feed_name"] == "Publications"
    assert report["published_at"] == "2026-09-28T00:00:00Z"  # the listing's date wins
    assert report["pdf_url"].endswith("/files/p1.pdf")
    assert report["image_url"].endswith("/img/p1-large.jpg")  # the page's share image beats the thumbnail
    assert report["language"] == "en" and report["word_count"] > 40
    news = next(a for a in stored if a["url"].endswith("/news/a1"))
    assert news["content_type"] == "news" and news["tags"] == "institute"
    assert db.scalar("SELECT last_scraped_at FROM sources WHERE id = ?", (source_id,))


def test_first_scrape_is_limited_and_updates_stop_when_caught_up(site, job):
    config.update({"max_pages_first": 2})
    source_id = add_source(Recipe(site_name="X", feeds=[
        listing_feed(site, pagination="next_link", next_selector="a.pager__next")]))

    first = scrape_source(source_id, job)
    assert first["new"] == 4 and first["feeds"][0]["pages"] == 2  # two listing pages, as configured

    Handler.hits.clear()
    second = scrape_source(source_id, job)
    assert second["new"] == 0
    assert Handler.hits == ["/publications"]  # one listing page, no article pages re-downloaded

    third = scrape_source(source_id, job, deep=True)
    assert third["new"] == 2  # deep scrape walks past known pages to the archive
    assert db.scalar("SELECT COUNT(*) FROM articles") == 6


def test_a_failing_item_does_not_stop_the_scrape(site, job):
    recipe = Recipe(site_name="X", feeds=[FeedRecipe(
        name="Mixed", connector="single", url=f"{site}/news/a1",
        options={"extra_urls": f"{site}/does-not-exist {site}/js-only {site}/news/a2"})])
    totals = scrape_source(add_source(recipe), job)
    assert totals["new"] == 2 and totals["failed"] == 2
    assert "HTTP 404" in job.text() and "JavaScript" in job.text()


def test_a_broken_feed_is_reported_but_others_continue(site, job):
    recipe = institute(site)
    recipe.feeds[0].options["item_selector"] = "article["
    source_id = add_source(recipe)
    totals = scrape_source(source_id, job)
    assert totals["new"] == 3
    assert "item_selector" in db.scalar("SELECT last_error FROM sources WHERE id = ?", (source_id,))


def test_scrape_fails_clearly_when_nothing_works(site, job):
    recipe = Recipe(site_name="X", feeds=[FeedRecipe(name="Gone", connector="rss", url=f"{site}/missing.xml")])
    with pytest.raises(JobError, match="HTTP 404"):
        scrape_source(add_source(recipe), job)
    with pytest.raises(JobError, match="no enabled feeds"):
        scrape_source(add_source(Recipe(site_name="Empty")), job)


def test_disabled_feeds_are_skipped(site, job):
    recipe = institute(site)
    recipe.feeds[0].enabled = False
    totals = scrape_source(add_source(recipe), job)
    assert [f["feed"] for f in totals["feeds"]] == ["News"]


# --- search --------------------------------------------------------------------------------

def titles(match: str, **kwargs) -> list[str]:
    return [a["title"] for a in query.search(match, **kwargs)["items"]]


def test_text_search_requires_every_word(scraped):
    assert titles(query.text_match("swarm defence")) == ["Drone swarms and the future of air defence"]
    assert len(titles(query.text_match("drone defence"))) == 2  # both words appear in the Anduril piece too
    assert len(titles(query.text_match("drone"))) == 2  # prefix: 'drone' also finds 'drones' in the Anduril piece
    assert titles(query.text_match('"critical infrastructure"')) == ["Cyber resilience for critical infrastructure"]
    assert titles(query.text_match("zebra")) == []


def test_search_ranks_title_matches_first_and_marks_snippets(scraped):
    found = query.search(query.text_match("drone"))["items"]
    assert found[0]["title"].startswith("Drone swarms")
    assert query.MARK_OPEN in found[0]["snippet"] and query.MARK_CLOSE in found[0]["snippet"]


def test_search_survives_punctuation_in_the_query(scraped):
    for text in ['drone"', "AND OR NOT", "(climate", "a*", "c++ / f-35", "'; DROP TABLE articles;--"]:
        query.search(query.text_match(text))  # must not raise an FTS syntax error
    assert db.scalar("SELECT COUNT(*) FROM articles") == 9


def test_topic_matching_broad_and_specific(scraped):
    broad = query.topic_match([], ["climate change", "klimaatverandering", "energietransitie"])
    assert set(titles(broad)) == {
        "Klimaatverandering en de energietransitie in Nederland",
        "Conference report: climate change adaptation in delta cities",
    }
    specific = query.topic_match(["Anduril"], ["drone", "autonomous"])
    assert titles(specific) == ["Anduril and the new defence industrial base"]
    assert query.count(specific) == 1
    assert query.topic_match([], []) == ""


def test_topic_sources_and_filters(scraped):
    match = query.topic_match([], ["drone", "unmanned"])
    sources = query.sources_for(match)
    assert sources[0]["name"] == "Example Institute" and sources[0]["matches"] == 3
    assert len(titles(match, content_type="news")) == 1
    assert titles(match, source_id=scraped + 99) == []


def test_newest_sort_and_paging(scraped):
    newest = query.search("", limit=4)
    assert newest["total"] == 9 and len(newest["items"]) == 4
    dates = [a["published_at"] for a in newest["items"]]
    assert dates == sorted(dates, reverse=True)
    rest = query.search("", limit=4, offset=8)
    assert len(rest["items"]) == 1


def test_deleting_an_article_removes_it_from_the_index(scraped):
    match = query.text_match("Anduril")
    assert query.count(match) == 1
    db.execute("DELETE FROM articles WHERE title LIKE 'Anduril%'")
    assert query.count(match) == 0


# --- scheduler -----------------------------------------------------------------------------

def test_scheduler_picks_sources_that_are_due(site):
    recipe = institute(site)
    now = datetime.now(timezone.utc)
    stamp = lambda minutes: (now - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    never = add_source(recipe, name="never scraped", interval_minutes=60)
    overdue = add_source(recipe, name="overdue", interval_minutes=60, last_scraped_at=stamp(90))
    add_source(recipe, name="fresh", interval_minutes=60, last_scraped_at=stamp(10))
    add_source(recipe, name="manual", interval_minutes=0)
    assert {s["id"] for s in scheduler.due_sources(now)} == {never, overdue}


def test_every_day_means_at_the_daily_scrape_time_dutch_time(site):
    recipe = institute(site)
    utc = lambda text: datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)  # noqa: E731
    stamp = lambda text: utc(text).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    last_night = add_source(recipe, name="last night", interval_minutes=1440, last_scraped_at=stamp("2026-11-03 21:58"))
    this_morning = add_source(recipe, name="this morning", interval_minutes=1440, last_scraped_at=stamp("2026-11-04 08:00"))
    hourly = add_source(recipe, name="hourly", interval_minutes=60, last_scraped_at=stamp("2026-11-04 12:30"))
    due = lambda when: {s["id"] for s in scheduler.due_sources(utc(when))}  # noqa: E731

    assert config.get("daily_scrape_time") == "15:00"  # 14:00 UTC in winter
    assert due("2026-11-04 13:59") == {hourly}
    assert due("2026-11-04 14:00") == {last_night, this_morning, hourly}
    db.execute("UPDATE sources SET last_scraped_at = ? WHERE interval_minutes = 1440", (stamp("2026-11-04 14:03"),))
    assert due("2026-11-05 13:59") == {hourly}  # once a day, not every 24 hours from 14:03
    assert due("2026-11-05 14:00") >= {last_night, this_morning}
    assert scheduler.daily_slot(utc("2026-07-01 13:30")) == utc("2026-07-01 13:00")  # 15:00 in summer is 13:00 UTC
    assert scheduler.daily_slot(utc("2026-07-01 12:59")) == utc("2026-06-30 13:00")  # before it: yesterday's

    config.update({"daily_scrape_time": "7.30"})
    assert config.get("daily_scrape_time") == "07:30"
    for wrong in ("25:00", "15", "noon"):
        with pytest.raises(ValueError):
            config.update({"daily_scrape_time": wrong})


# --- sites that refuse item pages but serve a feed ---------------------------------------------

class PagesBlocked(Context):
    """A site like many behind bot protection: the feed is served, every page answers 403."""

    def fetch(self, url, fetcher="http", **kwargs):
        if url.endswith("/feed.xml") or url.endswith("/robots.txt"):
            return super().fetch(url, fetcher, **kwargs)
        raise FetchError(f"HTTP 403 for {url}", refused=True)


def test_blocked_item_pages_fall_back_to_the_feed_text(site, job):
    recipe = Recipe(site_name="X", feeds=[FeedRecipe(name="News", connector="rss", url=f"{site}/feed.xml")])
    totals = scrape_source(add_source(recipe), job, ctx=PagesBlocked())
    assert totals["new"] == 3 and totals["failed"] == 0 and totals["feeds"][0]["partial"] == 3
    stored = db.rows("SELECT title, text, is_partial FROM articles ORDER BY url")
    assert stored[0]["text"] == "Short teaser for a1." and stored[0]["is_partial"] == 1
    assert job.text().count("cannot be read, so what the listing said is stored") == 1  # once, not per item


def test_feeds_configured_as_teaser_only_are_marked_partial_without_fetching(site, job):
    recipe = Recipe(site_name="X", feeds=[
        FeedRecipe(name="News", connector="rss", url=f"{site}/feed.xml", fetch_detail=False)])
    Handler.hits.clear()
    totals = scrape_source(add_source(recipe), job)
    assert totals["new"] == 3 and Handler.hits == ["/feed.xml"]  # no item page was requested
    assert db.scalar("SELECT COUNT(*) FROM articles WHERE is_partial = 1") == 3
    assert "cannot be read" not in job.text()  # nothing went wrong, so nothing to warn about


def test_quick_detect_works_from_the_feed_when_pages_are_blocked(site, job):
    analysis = analyzers.get("heuristic").analyze(f"{site}/", "", job, PagesBlocked())
    feed = analysis.recipe.feeds[0]
    assert (feed.connector, feed.url, feed.fetch_detail) == ("rss", f"{site}/feed.xml", False)
    report = analysis.recipe.structure_report
    assert "could not be opened (HTTP 403" in report and "article pages cannot be read" in report
    assert analysis.previews[feed.name]["total_items"] == 3


def test_feeds_are_read_even_when_robots_txt_bars_crawlers(site, job, monkeypatch):
    from backend.fetchers import fetchers

    http = fetchers.get("http")
    monkeypatch.setattr(http, "_allowed_by_robots", lambda url: False)  # a site whose robots.txt says Disallow: /
    with pytest.raises(FetchError, match="robots.txt"):
        http.fetch(f"{site}/news/a1")
    recipe = Recipe(site_name="X", feeds=[FeedRecipe(name="News", connector="rss", url=f"{site}/feed.xml")])
    totals = scrape_source(add_source(recipe), job)
    assert totals["new"] == 3 and totals["feeds"][0]["partial"] == 3  # feed read; item pages left alone


def test_feed_type_stands_unless_it_is_generic(site, job):
    def scrape_pdf(content_type: str) -> str:
        db.execute("DELETE FROM articles")
        recipe = Recipe(site_name="X", feeds=[FeedRecipe(name="Docs", connector="single", url=f"{site}/files/p1.pdf",
                                                         content_type=content_type)])
        scrape_source(add_source(recipe), job)
        return db.scalar("SELECT content_type FROM articles")

    assert scrape_pdf("paper") == "paper"  # what the recipe says the items are
    assert scrape_pdf("article") == "document"  # a generic type is refined by what was actually found


def test_a_deep_scrape_goes_back_as_many_items_as_asked(site, job):
    config.update({"max_pages_first": 1, "max_pages_deep": 1})
    source_id = add_source(Recipe(site_name="X", feeds=[
        listing_feed(site, pagination="next_link", next_selector="a.pager__next")]))
    assert scrape_source(source_id, job)["new"] == 2  # the first page

    Handler.hits.clear()
    totals = scrape_source(source_id, job, deep=True, limit=3)
    assert (totals["new"], totals["limit"], totals["reached"]) == (3, 3, True)
    assert totals["feeds"][0]["pages"] == 3  # the number asked for decides, not the one page a deep scrape may walk
    # the two that were stored are passed without being opened, and the sixth is not opened either
    assert [hit for hit in Handler.hits if hit.startswith("/publications/")] == ["/publications/p3", "/publications/p4",
                                                                                 "/publications/p5"]
    assert "until 3 more items are stored" in job.text() and "That is the 3 asked for" in job.text()

    more = scrape_source(source_id, job, deep=True, limit=10)  # more than the archive has left
    assert (more["new"], more["reached"]) == (1, False) and "The archive ran out before the 10 asked for" in job.text()
    assert db.scalar("SELECT COUNT(*) FROM articles") == 6

    plain = scrape_source(source_id, job, limit=5)  # a number does not make an update go back: it stays an update
    assert (plain["new"], plain["reached"]) == (0, False)


def test_the_number_asked_for_counts_across_feeds_and_is_taken_through_the_api(site):
    from fastapi.testclient import TestClient

    from backend.main import app
    from tests.test_api import wait_for

    source_id = add_source(institute(site))  # Publications (six, two a page), then News (three)
    with TestClient(app) as api:
        started = api.post(f"/api/sources/{source_id}/scrape", json={"deep": True, "limit": 2}).json()
        done = wait_for(api, started["job_id"])
        assert done["status"] == "done" and done["title"] == "Deep scrape (2 more): Example Institute"
        assert done["result"]["new"] == 2 and done["result"]["reached"] is True
        assert [feed["feed"] for feed in done["result"]["feeds"]] == ["Publications"]  # News was not needed
        assert "/feed.xml" not in Handler.hits and done["progress"]["total"] == 2

        rest = wait_for(api, api.post(f"/api/sources/{source_id}/scrape", json={"deep": True, "limit": 50}).json()["job_id"])
        assert rest["result"]["new"] == 7 and rest["result"]["reached"] is False
        assert api.post(f"/api/sources/{source_id}/scrape", json={"deep": True, "limit": -1}).status_code == 422
        everything = wait_for(api, api.post(f"/api/sources/{source_id}/scrape", json={"deep": True}).json()["job_id"])
        assert everything["title"] == "Deep scrape: Example Institute" and "limit" not in everything["result"]
        assert api.get("/api/meta").json()["scrape"]["seconds_per_item"] == 1.0  # the tests pause for nothing


def test_an_items_language_is_the_one_its_text_is_written_in():
    from backend.pipeline.scrape import _language

    english = ("What were the goals and outcomes of the talks between the two governments, and what do they mean "
               "for the support that has been promised for the coming year? The answer depends on the state of "
               "the front and on the money that is still to be found in the budget of the next year.")
    german = ("Der Krieg im Sudan dauert seit April 2023 an, und die Lage der Menschen in dem Land wird nach "
              "Angaben der Helfer von Woche zu Woche immer schlechter. Die Regierung und die Armee streiten um die "
              "Macht, und die Nachbarn sehen mit Sorge auf die Grenze und auf die Lager im Norden.")
    assert _language("pl", "Another crisis in US-Ukraine relations", "", english) == "en"  # PISM's label
    assert _language("de", "Der Krieg im Sudan", "", german) == "de"
    assert _language("ko", "Short", "", "Too short to tell.") == "ko"  # then the page's own word stands
    assert _language("", "Untitled", "", english) == "" and _language("en", "x", "", german) == "en"
