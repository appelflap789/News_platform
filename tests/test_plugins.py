"""Fetcher, connectors and extractors against the fake website."""

from __future__ import annotations

import pytest

from backend import config
from backend.connectors import ConnectorError, Context, connectors
from backend.dom import SelectorError
from backend.extractors import ExtractError, pick
from backend.fetchers import FetchError, fetchers
from backend.pipeline.scrape import preview_article, preview_feed
from backend.schemas import FeedRecipe, Recipe, validate_recipe
from backend.util import canonical_url, html_to_text, parse_date, registrable_domain
from tests.conftest import Handler

LISTING_OPTIONS = {
    "item_selector": "article.teaser",
    "link_selector": "a.teaser__link",
    "title_selector": ".teaser__title",
    "date_selector": "time",
    "summary_selector": ".teaser__summary",
}


def listing_feed(site: str, **options) -> FeedRecipe:
    return FeedRecipe(name="Publications", connector="html_list", url=f"{site}/publications",
                      content_type="report", options={**LISTING_OPTIONS, **options})


def pages_of(feed: FeedRecipe, limit: int = 10):
    pages = []
    for page in connectors.get(feed.connector).iter_pages(feed, Context()):
        pages.append(page)
        if len(pages) >= limit:
            break
    return pages


# --- helpers ---------------------------------------------------------------------------

def test_parse_date_understands_common_formats():
    assert parse_date("2026-09-28") == "2026-09-28T00:00:00Z"
    assert parse_date("2026-09-28T10:00:00+02:00") == "2026-09-28T08:00:00Z"
    assert parse_date("Mon, 05 Oct 2026 09:00:00 +0000") == "2026-10-05T09:00:00Z"
    assert parse_date("12 maart 2024").startswith("2024-03-12")
    assert parse_date("5 min read") == ""  # digits, but not a date
    assert parse_date("") == ""
    assert parse_date("0001-01-01") == ""  # implausible year
    assert parse_date("2024") == "2024-01-01T00:00:00Z"  # a bare year is kept, as the start of that year


def test_a_year_only_listing_date_yields_to_the_item_page():
    from backend.util import better_date

    assert better_date("2024-01-01T00:00:00Z", "2024-08-19T00:00:00Z") == "2024-08-19T00:00:00Z"
    assert better_date("2024-09-28T00:00:00Z", "2024-08-19T00:00:00Z") == "2024-09-28T00:00:00Z"
    assert better_date("2024-01-01T00:00:00Z", "") == "2024-01-01T00:00:00Z"
    assert better_date("", "2024-08-19T00:00:00Z") == "2024-08-19T00:00:00Z"


def test_canonical_url_drops_tracking_and_fragments():
    assert canonical_url("HTTPS://Example.org/a?utm_source=x&id=3&fbclid=1#top") == "https://example.org/a?id=3"
    assert canonical_url("https://example.org") == "https://example.org/"


def test_registrable_domain():
    assert registrable_domain("www.clingendael.org") == "clingendael.org"
    assert registrable_domain("news.bbc.co.uk") == "bbc.co.uk"


def test_html_to_text_keeps_sentences_together():
    text = html_to_text("<div><p>One <a href='#'>linked</a> sentence.</p><p>Two.</p><script>x()</script></div>")
    assert text == "One linked sentence.\n\nTwo."


# --- fetcher ---------------------------------------------------------------------------

def test_fetch_follows_redirects_and_reports_final_url(site):
    result = fetchers.get("http").fetch(f"{site}/redirect")
    assert result.url == f"{site}/publications"
    assert result.is_html and not result.is_pdf


def test_fetch_refuses_local_addresses_when_guard_is_on(site):
    config.update({"block_private_hosts": True})
    with pytest.raises(FetchError, match="local network"):
        fetchers.get("http").fetch(f"{site}/")


def test_a_bot_check_instead_of_the_page_is_called_by_its_name(site, job):
    with pytest.raises(FetchError, match="Imperva \\(Incapsula\\) bot check instead of the page") as raised:
        fetchers.get("http").fetch(f"{site}/walled")
    assert raised.value.refused is True
    # The wizard says so, instead of that it found no feed (as it did for www.pism.pl, whose check is copied
    # above as it came). There every address answers with the check, the feeds it tries included.
    from backend.analyzers import analyzers

    class Walled(Context):
        def fetch(self, url, fetcher="http", **kwargs):
            return fetchers.get("http").fetch(f"{site}/walled", **kwargs)

    with pytest.raises(FetchError, match="Incapsula"):
        analyzers.get("heuristic").analyze("https://www.pism.pl/publications", "", job, Walled())


def test_fetch_respects_robots_txt(site):
    with pytest.raises(FetchError, match="robots.txt"):
        fetchers.get("http").fetch(f"{site}/private/secret")
    config.update({"respect_robots": False})
    assert fetchers.get("http").fetch(f"{site}/private/secret").status == 200


def test_fetch_reports_http_errors(site):
    with pytest.raises(FetchError, match="HTTP 404"):
        fetchers.get("http").fetch(f"{site}/does-not-exist")


def test_fetch_enforces_size_limit(site):
    with pytest.raises(FetchError, match="larger than"):
        fetchers.get("http").fetch(f"{site}/publications", max_bytes=100)


# --- connectors ------------------------------------------------------------------------

def test_rss_connector_lists_entries(site):
    feed = FeedRecipe(name="News", connector="rss", url=f"{site}/feed.xml")
    pages = pages_of(feed)
    assert len(pages) == 1
    items = pages[0].items
    assert [i.url for i in items] == [f"{site}/news/a1", f"{site}/news/a2", f"{site}/news/a3"]
    assert items[0].title.startswith("Institute opens")
    assert items[0].published == "2026-10-05T09:00:00Z"
    assert items[0].tags == ["institute"]


def test_rss_connector_rejects_non_feeds(site):
    with pytest.raises(ConnectorError, match="not a readable"):
        pages_of(FeedRecipe(name="x", connector="rss", url=f"{site}/publications"))


@pytest.mark.parametrize("options", [
    {"pagination": "next_link", "next_selector": "a.pager__next"},
    {"pagination": "page_param", "page_param": "page", "page_start": "0"},
])
def test_html_list_walks_all_pages(site, options):
    pages = pages_of(listing_feed(site, **options))
    urls = [item.url for page in pages for item in page.items]
    assert urls == [f"{site}/publications/p{n}" for n in range(1, 7)]  # tracking parameter removed, no repeats
    first = pages[0].items[0]
    assert first.title == "Drone swarms and the future of air defence"
    assert first.published == "2026-09-28T00:00:00Z"
    assert first.summary.startswith("Autonomous drone swarms")
    assert first.image_url == f"{site}/img/p1.jpg"
    assert pages[0].diagnostics["elements_matching_item_selector"] == 2


def test_html_list_url_template_pagination(site):
    feed = listing_feed(site, pagination="url_template", page_template=f"{site}/publications?page={{page}}",
                        page_start="0")
    assert sum(len(p.items) for p in pages_of(feed)) == 6


def test_html_list_without_pagination_reads_one_page(site):
    assert len(pages_of(listing_feed(site))) == 1


def test_html_list_reports_bad_selectors(site):
    with pytest.raises(SelectorError, match="item_selector"):
        pages_of(listing_feed(site, item_selector="article["))
    with pytest.raises(ConnectorError, match="needs an item_selector"):
        pages_of(FeedRecipe(name="x", connector="html_list", url=f"{site}/publications"))


def test_sitemap_connector_filters_and_sorts(site):
    feed = FeedRecipe(name="All", connector="sitemap", url=f"{site}/sitemap.xml",
                      options={"url_pattern": "/publications/", "exclude_pattern": "p6$"})
    items = pages_of(feed)[0].items
    assert len(items) == 5
    assert all("/publications/" in i.url for i in items)
    assert items[0].published > items[-1].published  # newest first


def test_single_connector_yields_the_url_itself(site):
    feed = FeedRecipe(name="Doc", connector="single", url=f"{site}/files/p1.pdf",
                      options={"extra_urls": f"{site}/news/a1 not-a-url"})
    assert [i.url for i in pages_of(feed)[0].items] == [f"{site}/files/p1.pdf", f"{site}/news/a1"]


def test_reddit_connector_builds_feed_urls():
    from backend.connectors.reddit import feed_url

    assert feed_url("https://reddit.com/r/drones") == "https://www.reddit.com/r/drones/.rss"
    assert feed_url("https://old.reddit.com/r/drones/top/?t=week") == "https://www.reddit.com/r/drones/top/.rss?t=week"
    assert feed_url("https://www.reddit.com/r/drones/.rss") == "https://www.reddit.com/r/drones/.rss"
    with pytest.raises(ConnectorError):
        feed_url("https://www.reddit.com/")


# --- extractors ------------------------------------------------------------------------

def test_html_extractor_finds_text_and_metadata(site):
    result = fetchers.get("http").fetch(f"{site}/publications/p1")
    extractor = pick(result)
    assert extractor.name == "html"
    found = extractor.extract(result, {}, Context())
    assert found.title == "Drone swarms and the future of air defence"
    assert "Autonomous drone swarms" in found.text and "Second paragraph" in found.text
    assert "window.tracking" not in found.text and "Contact" not in found.text
    assert found.published.startswith("2026-09-28")
    assert found.image_url == f"{site}/img/p1-large.jpg"
    assert found.pdf_url == f"{site}/files/p1.pdf"  # found without a selector, inside the article
    assert found.language == "en"


def test_html_extractor_tidies_keywords():
    from backend.extractors.html_article import _tags

    assert _tags(["Russia, Brexit", "Russia", " Brexit ", "UK;EU"]) == ["Russia", "Brexit", "UK", "EU"]
    assert _tags(None) == [] and _tags("Russia") == []


def test_html_extractor_selectors_override(site):
    result = fetchers.get("http").fetch(f"{site}/publications/p1")
    found = pick(result).extract(result, {"author_selector": ".byline", "body_selector": "div.body"}, Context())
    assert found.author == "Jane Researcher"
    assert found.text.startswith("Autonomous drone swarms")


def test_html_extractor_can_read_the_linked_pdf(site):
    result = fetchers.get("http").fetch(f"{site}/publications/p1")
    found = pick(result).extract(result, {"extract_pdf_text": "true"}, Context())
    assert "Line 12 of the full report" in found.text
    assert found.content_type == "report"
    assert found.summary  # the page text is kept as the summary


def test_html_extractor_flags_pages_without_text(site):
    result = fetchers.get("http").fetch(f"{site}/js-only")
    with pytest.raises(ExtractError, match="JavaScript"):
        pick(result).extract(result, {}, Context())


def test_pdf_extractor(site):
    result = fetchers.get("http").fetch(f"{site}/files/p1.pdf")
    extractor = pick(result)
    assert extractor.name == "pdf"
    found = extractor.extract(result, {}, Context())
    assert found.title == "Drone swarms full report"
    assert found.content_type == "document"
    assert "Line 1 of the full report" in found.text


# --- previews and recipe validation ----------------------------------------------------------

def test_preview_feed_reports_pages(site):
    preview = preview_feed(listing_feed(site, pagination="next_link", next_selector="a.pager__next"), pages=2)
    assert preview["total_items"] == 4
    assert [p["items"] for p in preview["pages"]] == [2, 2]
    assert preview["pages"][0]["next_page_url"] == f"{site}/publications?page=1"
    assert preview["items"][0]["title"].startswith("Drone swarms")


def test_preview_article(site):
    preview = preview_article(f"{site}/news/a1", {})
    assert preview["extractor"] == "html"
    assert preview["text_characters"] > 200


def test_recipe_validation_names_the_problem(site):
    good = Recipe(site_name="Example", feeds=[listing_feed(site)])
    validate_recipe(good)
    bad = Recipe(site_name="Example", feeds=[
        FeedRecipe(name="A", connector="carrier-pigeon", url="ftp://x"),
        FeedRecipe(name="B", connector="rss", url=f"{site}/feed.xml", options={"item_selector": "li"}),
    ])
    with pytest.raises(ValueError) as error:
        validate_recipe(bad)
    message = str(error.value)
    assert "unknown connector 'carrier-pigeon'" in message
    assert "http://" in message
    assert "does not use option(s) item_selector" in message


def test_options_are_normalised_to_strings():
    feed = FeedRecipe(name="x", connector="html_list", url="https://e.org",
                      options={"page_start": 0, "page_step": 20, "next_selector": "", "x": None, "flag": True})
    assert feed.options == {"page_start": "0", "page_step": "20", "flag": "true"}
    assert feed.opt_int("page_step", 1) == 20 and feed.opt_int("missing", 7) == 7


def test_fixture_site_counts_requests(site):
    fetchers.get("http").fetch(f"{site}/news/a1")
    assert "/news/a1" in Handler.hits
