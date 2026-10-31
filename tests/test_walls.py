"""Items behind a login or a paywall: recognising them, and leaving them out when a source says so."""

from __future__ import annotations

import time

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from backend import config, db
from backend.connectors import connectors
from backend.extractors import _walls
from backend.fetchers import FetchError
from backend.main import app
from backend.pipeline.scrape import LeftOut, _lasting, scrape_source
from backend.schemas import FeedRecipe, Recipe
from backend.util import word_count
from tests.conftest import Handler, TEASER, premium
from tests.test_pipeline import add_source
from tests.test_reddit import ARTICLE, ATLANTIC, AXIOS, LISTING, PAYWALL, WSJ, Reddit, reddit_feed

READABLE = ["free", "free-short", "long-declared"]
WALLED = ["declared", "forbidden", "gate", "login-needed"]  # no use asking for these again
ALL = sorted([*READABLE, *WALLED, "busy"])


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def premium_source(site: str, **columns) -> int:
    recipe = Recipe(site_name="Premium", homepage=site, language="en", feeds=[
        FeedRecipe(name="Premium", connector="rss", url=f"{site}/premium.xml", content_type="news")])
    return add_source(recipe, **columns)


def slugs(where: str = "1 = 1") -> list[str]:
    return sorted(row["url"].rsplit("/", 1)[-1] for row in db.rows(f"SELECT url FROM articles WHERE {where}"))


def left_out() -> dict[str, str]:
    return {row["url"].rsplit("/", 1)[-1]: row["reason"] for row in db.rows("SELECT url, reason FROM left_out")}


def wall(html: str, url: str = "https://example.org/news/item", text: str | None = None) -> str:
    return _walls.on_page(url, BeautifulSoup(html, "lxml"), TEASER if text is None else text)


# --- recognising a wall ----------------------------------------------------------------------

def test_a_page_that_says_it_is_not_free_and_shows_little_is_walled():
    assert wall(premium("declared")) == f"the page says it is for subscribers and shows {word_count(TEASER)} words"
    assert wall(premium("free")) == ""
    locked = '<meta property="article:content_tier" content="locked">'
    assert "for subscribers" in wall(f"{locked}<p>x</p>")
    assert wall('<meta property="article:content_tier" content="free"><p>x</p>') == ""
    assert "for subscribers" in wall('<div itemscope><meta itemprop="isAccessibleForFree" content="false"></div>')
    assert wall('<script type="application/ld+json">this is not JSON</script><p>x</p>') == ""

    # Seen on real sites: the value written as an address, the free opening of a paid article marked "true",
    # and a site that calls every page "locked" while saying of this one that it is free.
    as_address = ('<script type="application/ld+json">{"@type": "NewsArticle", "isAccessibleForFree": '
                  '"http://schema.org/False", "hasPart": {"isAccessibleForFree": "http://schema.org/True"}}</script>')
    assert "for subscribers" in wall(as_address)
    free = '<script type="application/ld+json">{"@type": "NewsArticle", "isAccessibleForFree": true}</script>'
    assert wall(free) == "" and wall(locked + free) == ""


def test_a_page_that_shows_little_and_asks_to_log_in_or_subscribe_is_walled():
    assert wall(premium("gate")) == (f'the page shows {word_count(TEASER)} words and then asks to log in or '
                                    f'subscribe ("subscribe to continue")')
    for phrase in ("Log in om verder te lezen", "Dit artikel is alleen voor abonnees.", "Jetzt weiterlesen mit Plus",
                   "Cet article est réservé aux abonnés", "Create a free account to keep going"):
        assert wall(f"<main><p>{TEASER}</p><div>{phrase}</div></main>"), phrase
    # "Subscribe" and "log in" are on every page of a news site; by themselves they say nothing.
    assert wall(f"<main><p>{TEASER}</p><a>Subscribe</a> <a>Log in</a> <p>Subscribe to our newsletter</p></main>") == ""


def test_what_the_header_and_footer_say_does_not_count():
    assert wall(premium("free-short")) == ""  # "Subscribe to read everything" is in the page's header


def test_a_text_that_could_be_read_is_never_walled():
    words = lambda count: " ".join(["word"] * count)
    assert wall(premium("gate"), text=words(_walls.SHORT_WORDS)) == ""
    assert wall(premium("gate"), text=words(_walls.SHORT_WORDS - 1)) != ""
    # A page that says of itself that it is paid has to show more before it is believed to be whole.
    assert wall(premium("long-declared"), text=words(_walls.SHORT_WORDS)) != ""
    assert wall(premium("long-declared"), text=words(_walls.SHORT_WORDS_NOT_FREE)) == ""


def test_an_address_that_ends_on_a_login_page_is_walled():
    assert wall("<p>x</p>", "https://example.org/login?next=/news/item") == "its address leads to a login page"
    assert wall("<p>x</p>", "https://example.org/account/sign-in") != ""
    assert wall("<p>x</p>", "https://example.org/news/how-to-log-in-to-your-router") == ""  # a word in a title


def test_which_failures_are_worth_trying_again():
    lasting = lambda status, refused=False: _lasting(FetchError("x", refused=refused, status=status))
    assert all(lasting(status) for status in (401, 402, 403, 404, 410, 451))
    assert not any(lasting(status, refused=status in (429, 503)) for status in (429, 500, 502, 503))
    assert lasting(0, refused=True)  # robots.txt says no, or a bot challenge
    assert not lasting(0)  # a timeout
    assert LeftOut("no text").lasting


# --- what a scrape does with them ------------------------------------------------------------

def test_without_the_option_everything_is_stored_and_what_is_behind_a_wall_is_marked_partial(site, job):
    totals = scrape_source(premium_source(site), job)
    assert totals["new"] == 8 and totals["left_out"] == 0 and totals["feeds"][0]["partial"] == 5
    assert slugs() == ALL and slugs("is_partial = 1") == sorted([*WALLED, "busy"])
    assert db.scalar("SELECT COUNT(*) FROM left_out") == 0
    texts = {row["url"].rsplit("/", 1)[-1]: row["text"] for row in db.rows("SELECT url, text FROM articles")}
    assert "The ministry announced" in texts["declared"]  # what the page shows in front of its paywall
    assert texts["forbidden"] == "Short teaser for forbidden."  # the page refused: what the feed said
    assert "behind a login or paywall" in job.text() and "Settings tab" in job.text()


def test_with_the_option_what_cannot_be_read_is_left_out(site, job):
    source_id = premium_source(site, skip_walled=1)
    totals = scrape_source(source_id, job)
    assert totals["new"] == 3 and totals["left_out"] == 5 and totals["failed"] == 0
    assert totals["feeds"][0]["left_out"] == 5 and totals["feeds"][0]["partial"] == 0
    assert slugs() == READABLE and slugs("is_partial = 1") == []

    reasons = left_out()
    assert sorted(reasons) == WALLED  # the busy server is not held against the item
    assert reasons["declared"].startswith("the page says it is for subscribers and shows ")
    assert "asks to log in or subscribe" in reasons["gate"]
    assert "its address leads to a login page" in reasons["login-needed"]
    assert reasons["forbidden"].startswith("HTTP 403")
    log = job.text()
    assert log.count("are left out, because their own page cannot be read") == 1  # once per site
    assert "Done: 3 new, 0 skipped, 5 left out because their own page cannot be read." in log

    # The next scrape opens the item that failed for a passing reason, and none of the others.
    Handler.hits.clear()
    again = scrape_source(source_id, job)
    assert Handler.hits == ["/premium.xml", "/premium/busy"]
    assert again["new"] == 0 and again["left_out"] == 1


def test_articles_shared_on_reddit_can_leave_out_the_ones_that_cannot_be_read(job):
    ctx = Reddit({AXIOS: ARTICLE, ATLANTIC: PAYWALL})
    config.update({"max_pages_first": 1})
    source_id = add_source(Recipe(site_name="r/geopolitics", homepage="https://www.reddit.com/r/geopolitics",
                                  language="en", feeds=[reddit_feed("articles")]), skip_walled=1)
    totals = scrape_source(source_id, job, ctx=ctx)
    assert totals["new"] == 1 and totals["left_out"] == 21  # the same listing stores 22 without the option
    assert slugs("is_partial = 1") == [] and db.scalar("SELECT url FROM articles") == AXIOS
    reasons = {row["url"]: row["reason"] for row in db.rows("SELECT url, reason FROM left_out")}
    assert reasons[WSJ].startswith("HTTP 403") and "almost no text" in reasons[ATLANTIC]

    asked = len(ctx.asked)
    connectors.get("reddit").forget()  # it keeps a listing page for two minutes
    scrape_source(source_id, job, ctx=ctx)
    assert [url for url, _ in ctx.asked[asked:]] == [LISTING]  # none of the 21 is asked for again


# --- the dashboard's side --------------------------------------------------------------------

def wait_for(api: TestClient, job_id: str) -> dict:
    deadline = time.time() + 30
    while time.time() < deadline:
        job = api.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def scrape(api: TestClient, source_id: int) -> dict:
    return wait_for(api, api.post(f"/api/sources/{source_id}/scrape", json={}).json()["job_id"])


def test_the_option_is_chosen_when_a_source_is_added_and_can_be_changed_later(api, site):
    recipe = {"site_name": "Premium", "homepage": site, "language": "en", "feeds": [
        {"name": "Premium", "connector": "rss", "url": f"{site}/premium.xml", "content_type": "news"}]}
    created = api.post("/api/sources", json={"url": f"{site}/", "recipe": recipe, "skip_walled": True}).json()
    job = wait_for(api, created["job_id"])
    assert job["status"] == "done" and job["result"]["left_out"] == 5

    source = api.get(f"/api/sources/{created['id']}").json()
    assert source["skip_walled"] is True and source["article_count"] == 3 and source["partial_stored"] == 0
    assert source["left_out"]["count"] == 4
    assert {entry["title"] for entry in source["left_out"]["recent"]} >= {"Coastal defence: the documents"}
    assert api.get("/api/sources").json()[0]["skip_walled"] is True

    # Switched off, the same items are stored after all, marked as partial.
    assert api.patch(f"/api/sources/{created['id']}", json={"skip_walled": False}).json()["skip_walled"] is False
    assert scrape(api, created["id"])["result"]["new"] == 5
    source = api.get(f"/api/sources/{created['id']}").json()
    assert source["article_count"] == 8 and source["partial_stored"] == 5

    # Switched on again, the partial items that were stored meanwhile can be removed; they do not come back.
    api.patch(f"/api/sources/{created['id']}", json={"skip_walled": True})
    assert api.post(f"/api/sources/{created['id']}/partial/remove").json() == {"removed": 5}
    assert slugs() == READABLE
    result = scrape(api, created["id"])["result"]
    assert result["new"] == 0 and result["left_out"] == 0 and slugs() == READABLE

    # "Try them again" forgets the list: the next scrape opens every one of them once more.
    assert api.post(f"/api/sources/{created['id']}/left-out/forget").json() == {"forgotten": 5}
    assert scrape(api, created["id"])["result"]["left_out"] == 5
    assert api.post("/api/sources/99999/left-out/forget").status_code == 404


def test_a_feed_that_stores_teasers_on_purpose_is_left_alone(api, site, job):
    recipe = Recipe(site_name="Premium", homepage=site, language="en", feeds=[
        FeedRecipe(name="Premium", connector="rss", url=f"{site}/premium.xml", fetch_detail=False)])
    source_id = add_source(recipe, skip_walled=1)
    totals = scrape_source(source_id, job)
    assert totals["new"] == 8 and totals["left_out"] == 0  # no item page is opened, so nothing is found out
    source = api.get(f"/api/sources/{source_id}").json()
    assert source["partial_stored"] == 0  # these are teasers by design, not items that could not be read
    assert api.post(f"/api/sources/{source_id}/partial/remove").json() == {"removed": 0}
    assert db.scalar("SELECT COUNT(*) FROM articles") == 8


def test_an_older_library_gets_the_option_switched_off(api, site):
    source_id = premium_source(site)
    db.execute("ALTER TABLE sources DROP COLUMN skip_walled")
    db.execute("DROP TABLE left_out")
    db.init()
    source = api.get(f"/api/sources/{source_id}").json()
    assert source["skip_walled"] is False and source["left_out"] == {"count": 0, "recent": []}
