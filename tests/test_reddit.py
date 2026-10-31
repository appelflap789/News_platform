"""The Reddit connector, driven by feeds saved from the real r/geopolitics (one listing of 25 posts, its second
page, and the comment feed of one post), so no internet is needed. The articles the posts link to are faked."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config, db
from backend.ai import client as ai
from backend.analyzers import analyzers
from backend.connectors import ConnectorError, Context, connectors
from backend.connectors.reddit import comments_url, discussion_url, shares_an_article
from backend.fetchers import FetchError, FetchResult
from backend.main import app
from backend.pipeline import comments
from backend.pipeline.scrape import preview_feed, scrape_source
from backend.schemas import FeedRecipe, Recipe, validate_recipe
from tests.conftest import FILLER, page
from tests.test_api import wait_for
from tests.test_pipeline import add_source

FIXTURES = Path(__file__).parent / "fixtures" / "reddit"
SUBREDDIT = "https://www.reddit.com/r/geopolitics/"
LISTING = "https://www.reddit.com/r/geopolitics/.rss"
PAGE_2 = "https://www.reddit.com/r/geopolitics/.rss?after=t3_1x1z1qv"
AXIOS = "https://www.axios.com/2026/10/10/trump-ukraine-zelensky-replace-putin-diesel"
AXIOS_POST = "https://www.reddit.com/r/geopolitics/comments/1x2m1i6/trump_tells_ukraine_to_replace_zelensky_over/"
WSJ = ("https://www.wsj.com/politics/policy/trump-strikes-deal-with-putin-for-russian-diesel-15751436"
       "?st=Dg55js&reflink=desktopwebshare_permalink")
WSJ_POST = "https://www.reddit.com/r/geopolitics/comments/1x21paw/trump_strikes_deal_with_putin_for_russian_diesel/"
ATLANTIC = "https://www.theatlantic.com/international/2026/10/french-decline-politics-extremism/688953/"
AMA_POST = "https://www.reddit.com/r/geopolitics/comments/1x1ilqg/ama_why_is_the_far_right_on_the_rise_in_europe/"
ARTICLE = page("Trump tells Ukraine to replace Zelensky", "<main><article><h1>Trump tells Ukraine to replace Zelensky"
               f"</h1><p>The president said so on Saturday.{FILLER}</p><p>Kyiv answered within hours.{FILLER}</p>"
               "</article></main>")
PAYWALL = page("Subscribe", "<main><article><h1>The French Are Very Worried</h1><p>Subscribe to keep reading. This "
               "story is available to subscribers only, so please sign in to your account or choose one of our "
               "subscription offers below to continue reading this article and thousands of others like it.</p>"
               "</article></main>")
TEXT_ONLY = """<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>ask</title>
<entry><author><name>/u/someone</name></author><content type="html">&lt;div class="md"&gt;&lt;p&gt;What do you
think will happen next?&lt;/p&gt;&lt;/div&gt; submitted by &lt;a href="https://www.reddit.com/user/someone"&gt;
/u/someone &lt;/a&gt; &lt;span&gt;&lt;a href="https://www.reddit.com/r/ask/comments/abc/a_question/"&gt;[link]&lt;/a&gt;
&lt;/span&gt; &lt;span&gt;&lt;a href="https://www.reddit.com/r/ask/comments/abc/a_question/"&gt;[comments]&lt;/a&gt;
&lt;/span&gt;</content><id>t3_abc</id><link href="https://www.reddit.com/r/ask/comments/abc/a_question/" />
<updated>2026-10-10T10:00:00+00:00</updated><title>A question about the coming months</title></entry></feed>"""


class Reddit(Context):
    """Reddit's feeds from the saved files, and whatever `pages` says for the sites the posts link to. Any other
    article address is refused, the way a paywalled newspaper refuses a scraper."""

    def __init__(self, pages: dict[str, str] | None = None) -> None:
        self.pages = pages or {}
        self.asked: list[tuple[str, bool]] = []  # (url, robots)

    def fetch(self, url: str, fetcher: str = "http", **kwargs) -> FetchResult:
        self.asked.append((url, kwargs.get("robots", True)))
        if url in self.pages:
            return FetchResult(url, 200, "text/html", self.pages[url].encode("utf-8"), "utf-8")
        if url == LISTING:
            return self._feed("listing.xml", url)
        if url == PAGE_2:
            return self._feed("listing_page2.xml", url)
        if url.startswith("https://www.reddit.com/") and "/comments/" in url and "/.rss?" in url:
            return self._feed("comments.xml", url)
        raise FetchError(f"HTTP 403 for {url}", refused=True)

    @staticmethod
    def _feed(name: str, url: str) -> FetchResult:
        return FetchResult(url, 200, "application/atom+xml", (FIXTURES / name).read_bytes(), "utf-8")

    def to(self, part: str) -> list[str]:
        return [url for url, _ in self.asked if part in url]


def reddit_feed(collect: str = "posts", url: str = SUBREDDIT, **options) -> FeedRecipe:
    return FeedRecipe(name="Reddit", connector="reddit", url=url, fetch_detail=False,
                      content_type="article" if collect == "articles" else "post",
                      options={"collect": collect, **options})


def first_page(feed: FeedRecipe, ctx: Context):
    return next(connectors.get("reddit").iter_pages(feed, ctx))


def scrape(feed: FeedRecipe, ctx: Context, job) -> dict:
    config.update({"max_pages_first": 1})
    source_id = add_source(Recipe(site_name="r/geopolitics", homepage=SUBREDDIT, language="en", feeds=[feed]))
    return scrape_source(source_id, job, ctx=ctx)


def stored(url: str):
    return db.row("SELECT * FROM articles WHERE url = ?", (url,))


# --- listing ---------------------------------------------------------------------------------

def test_posts_are_listed_with_their_text_and_the_link_they_share():
    ctx = Reddit()
    page_one = first_page(reddit_feed(), ctx)
    assert len(page_one.items) == 25 and page_one.diagnostics == {"entries_in_feed": 25}
    assert ctx.asked == [(LISTING, False)]  # the feed is read as a feed: robots.txt is for crawlers

    ama = page_one.items[0]
    assert ama.url == AMA_POST and ama.author == "guardian" and ama.published == "2026-10-09T11:12:34Z"
    assert ama.title.startswith("AMA: Why is the far right on the rise in Europe?")
    assert "we are Jon Henley" in ama.content_html and "Link:" not in ama.content_html
    assert "submitted by" not in ama.content_html and "[comments]" not in ama.content_html

    bare_link = next(item for item in page_one.items if item.url == WSJ_POST)
    assert bare_link.content_html == f"<p>Link: {WSJ.replace('&', '&amp;')}</p>"
    with_text = next(item for item in page_one.items if item.url == AXIOS_POST)
    assert "President Trump called Saturday" in with_text.content_html and f"Link: {AXIOS}" in with_text.content_html
    assert with_text.image_url.startswith("https://external-preview.redd.it/") and with_text.tags == ["geopolitics"]


def test_shared_articles_are_listed_by_the_address_of_the_article():
    page_one = first_page(reddit_feed("articles"), Reddit())
    assert page_one.diagnostics == {"entries_in_feed": 25, "sharing_an_article": 22}
    urls = [item.url for item in page_one.items]
    assert AXIOS in urls and WSJ in urls
    assert ATLANTIC in urls  # the utm_ tracking the poster left on the link is gone
    assert not any("reddit.com" in url or "streamable.com" in url for url in urls)  # no text posts, no video

    axios = page_one.items[urls.index(AXIOS)]
    assert axios.title == "Trump tells Ukraine to replace Zelensky over Russia fuel deal"
    assert axios.author == ""  # the article's own author is wanted, not the person who posted it
    assert axios.published == "2026-10-10T18:14:16Z"
    assert axios.extra == {"post": AXIOS_POST, "shared": f"Shared in r/geopolitics by u/John3262005: {AXIOS_POST}"}


def test_what_counts_as_an_article():
    assert shares_an_article("https://www.clingendael.org/publication/some-report")
    assert shares_an_article("https://example.org/files/report.pdf")
    for link in ("https://www.reddit.com/r/geopolitics/comments/abc/x/", "https://i.redd.it/abc.jpg",
                 "https://youtu.be/abc", "https://www.youtube.com/watch?v=abc", "https://x.com/someone/status/1",
                 "https://example.org/map.png", "https://streamable.com/06y53z", "", "mailto:someone@example.org"):
        assert not shares_an_article(link), link


def test_the_listing_is_paged_and_a_page_is_not_downloaded_twice():
    ctx = Reddit()
    connector = connectors.get("reddit")
    pages = []
    for listed in connector.iter_pages(reddit_feed(), ctx):
        pages.append(listed)
        if len(pages) == 2:
            break
    assert [len(p.items) for p in pages] == [25, 25] and pages[1].url == PAGE_2
    assert len({item.url for p in pages for item in p.items}) == 50
    # the second feed of the same subreddit, a moment later, costs Reddit nothing
    assert len(first_page(reddit_feed("articles"), ctx).items) == 22
    assert ctx.to(".rss") == [LISTING, PAGE_2]
    connector.forget()
    first_page(reddit_feed("articles"), ctx)
    assert ctx.to(".rss") == [LISTING, PAGE_2, LISTING]


def test_a_page_without_shared_articles_says_so(job):
    ctx = Reddit({"https://www.reddit.com/r/ask/.rss": TEXT_ONLY})
    feed = reddit_feed("articles", url="https://www.reddit.com/r/ask")
    listed = first_page(feed, ctx)
    assert listed.items == [] and "none of the 1 posts on this page shares an article" in listed.diagnostics["note"]
    assert preview_feed(feed, ctx)["total_items"] == 0
    assert scrape(feed, ctx, job)["new"] == 0
    assert "none of the 1 posts on this page shares an article" in job.text()
    assert len(first_page(reddit_feed(url="https://www.reddit.com/r/ask"), ctx).items) == 1  # as posts it lists fine


def test_options_are_checked():
    validate_recipe(Recipe(site_name="r/geopolitics", feeds=[reddit_feed("articles", comments="10")]))
    with pytest.raises(ConnectorError, match="'collect' must be one of posts, articles"):
        first_page(reddit_feed("everything"), Reddit())
    assert comments_url(AXIOS_POST, 30) == ("https://www.reddit.com/r/geopolitics/comments/1x2m1i6/"
                                            "trump_tells_ukraine_to_replace_zelensky_over/.rss"
                                            "?sort=top&depth=1&limit=31")


# --- scraping --------------------------------------------------------------------------------

def test_posts_without_comments_are_stored_from_the_listing_alone(job):
    ctx = Reddit()
    totals = scrape(reddit_feed(), ctx, job)
    assert totals["new"] == 25 and totals["failed"] == 0
    assert ctx.asked == [(LISTING, False)]  # one request for 25 posts

    ama = stored(AMA_POST)
    assert ama["content_type"] == "post" and ama["author"] == "guardian" and not ama["is_partial"]
    assert ama["text"].startswith("Hi r/geopolitics, we are Jon Henley") and "submitted by" not in ama["text"]
    assert ama["summary"].startswith("Hi r/geopolitics, we are Jon Henley") and ama["word_count"] > 300
    assert stored(WSJ_POST)["text"] == f"Link: {WSJ}"


def test_posts_are_stored_with_their_highest_voted_comments(job):
    ctx = Reddit()
    totals = scrape(reddit_feed(comments="5"), ctx, job)
    assert totals["new"] == 25 and totals["failed"] == 0
    assert len(ctx.to("/comments/")) == 25  # one comment feed per post
    assert (comments_url(AXIOS_POST, 5), False) in ctx.asked

    paragraphs = stored(AXIOS_POST)["text"].split("\n\n")
    start = paragraphs.index("Comments on Reddit, highest voted first (5)")
    assert paragraphs[start - 1] == f"Link: {AXIOS}"
    assert paragraphs[0].startswith("President Trump called Saturday for Ukraine to replace")
    comments = paragraphs[start + 1:]
    assert comments[0] == ("u/crab_races: Do you want to make Zelenskyy more popular with Ukranians? Because this "
                           "is how you make Zelenskyy more popular with Ukranians.")
    assert comments[1] == "u/BlueCollarLawyer: Trump is your enemy. Always was, always will be."
    assert len([c for c in comments if c.startswith("u/")]) == 5
    assert not any(c.startswith("u/John3262005: President Trump called") for c in comments)  # the post is no comment
    assert not stored(AXIOS_POST)["is_partial"]


def test_a_post_whose_comments_cannot_be_read_is_kept_as_partial(job):
    class NoComments(Reddit):
        def fetch(self, url, fetcher="http", **kwargs):
            if "/comments/" in url:
                raise FetchError(f"HTTP 429 for {url}", refused=True)
            return super().fetch(url, fetcher, **kwargs)

    totals = scrape(reddit_feed(comments="5"), NoComments(), job)
    assert totals["new"] == 25 and totals["feeds"][0]["partial"] == 25
    kept = stored(AXIOS_POST)
    assert kept["is_partial"] and kept["text"].startswith("President Trump called Saturday")
    assert "HTTP 429" in job.text()


def test_shared_articles_are_read_from_their_own_site(job):
    ctx = Reddit({AXIOS: ARTICLE, ATLANTIC: PAYWALL})
    totals = scrape(reddit_feed("articles"), ctx, job)
    assert totals["new"] == 22 and totals["failed"] == 0
    assert ctx.to(".rss") == [LISTING]  # nothing more is asked of Reddit
    assert (AXIOS, True) in ctx.asked  # the article's site is crawled, so its robots.txt counts

    article = stored(AXIOS)
    assert article["title"] == "Trump tells Ukraine to replace Zelensky over Russia fuel deal"
    assert article["content_type"] == "article" and not article["is_partial"]
    assert article["published_at"] == "2026-10-10T18:14:16Z" and article["author"] != "John3262005"
    paragraphs = article["text"].split("\n\n")
    assert paragraphs[1].startswith("The president said so on Saturday.") and "Kyiv answered" in paragraphs[2]
    assert paragraphs[-1] == f"Shared in r/geopolitics by u/John3262005: {AXIOS_POST}"
    assert "President Trump called Saturday" not in article["text"]  # the post's own text is not repeated
    assert stored(AXIOS_POST) is None  # the post itself is not an item in this mode

    refused = stored(WSJ)  # the site turned the scraper away: the item is kept, with where it was shared
    assert refused["is_partial"] and refused["title"] == "Trump Strikes Deal With Putin for Russian Diesel"
    assert refused["text"] == f"Shared in r/geopolitics by u/Unfair-Ticket9474: {WSJ_POST}"
    thin = stored(ATLANTIC)  # the site answered, but with a subscribe box instead of the article
    assert thin["is_partial"] and "Subscribe to keep reading" not in thin["text"]
    assert totals["feeds"][0]["partial"] == 21
    log = job.text()  # every site that could not be read is named once, with the reason
    assert "pages of www.theatlantic.com cannot be read" in log and "shows a scraper almost no text" in log
    assert log.count("pages of www.axios.com cannot be read") == 1  # two of its articles were refused
    assert "pages of www.wsj.com cannot be read" in log and "HTTP 403" in log


def test_shared_articles_can_carry_the_discussion(job):
    ctx = Reddit({AXIOS: ARTICLE})
    scrape(reddit_feed("articles", comments="3"), ctx, job)
    assert ctx.to("/comments/") == [comments_url(AXIOS_POST, 3)]  # only for the article that could be read
    paragraphs = stored(AXIOS)["text"].split("\n\n")
    start = paragraphs.index("Comments on Reddit, highest voted first (3)")
    assert paragraphs[start - 1] == f"Shared in r/geopolitics by u/John3262005: {AXIOS_POST}"
    assert paragraphs[start + 1].startswith("u/crab_races: ")
    assert len([p for p in paragraphs[start + 1:] if p.startswith("u/")]) == 3


def test_an_update_stops_at_what_is_already_stored(job):
    ctx = Reddit({AXIOS: ARTICLE})
    feed = reddit_feed("articles")
    source_id = add_source(Recipe(site_name="r/geopolitics", homepage=SUBREDDIT, feeds=[feed]))
    config.update({"max_pages_first": 1})
    assert scrape_source(source_id, job, ctx=ctx)["new"] == 22
    asked = len(ctx.asked)
    connectors.get("reddit").forget()
    again = scrape_source(source_id, job, ctx=ctx)
    assert again["new"] == 0 and again["feeds"][0]["pages"] == 1
    assert [url for url, _ in ctx.asked[asked:]] == [LISTING]  # refused articles are not asked for again


# --- adding a subreddit ----------------------------------------------------------------------

def test_quick_detect_offers_both_ways_of_collecting(job):
    ctx = Reddit()
    analysis = analyzers.get("heuristic").analyze(SUBREDDIT, "", job, ctx)
    recipe = analysis.recipe
    validate_recipe(recipe)
    assert recipe.site_name == "r/geopolitics"
    assert [(f.name, f.enabled, f.content_type, f.options) for f in recipe.feeds] == [
        ("Shared articles", True, "article", {"collect": "articles"}),
        ("Posts and comments", False, "post", {"collect": "posts", "comments": "30"}),
    ]
    assert analysis.previews["Shared articles"]["total_items"] == 22
    assert analysis.previews["Posts and comments"]["total_items"] == 25
    assert ctx.asked == [(LISTING, False)]  # both samples from one request
    assert "about one request a minute" in recipe.structure_report


# --- what the comments say: summed up on request ---------------------------------------------------

SUMMARY = ("Most commenters think the demand will backfire.\n\n## The main lines\n- Several say it makes Zelensky "
           "more popular at home.\n\n## Where they disagree\n- One or two defend the deal.")


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def claude_sums_up(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    def fake_structured(*, model, usage=None, **request):
        sent.append({**request, "model": model})
        if usage is not None:
            usage.add(model, type("U", (), {"input_tokens": 4000, "output_tokens": 300})())
        return {"summary": SUMMARY}

    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "client", lambda: None)
    monkeypatch.setattr(ai, "structured", fake_structured)
    return sent


def test_an_item_knows_the_reddit_post_it_belongs_to(api, job):
    scrape(reddit_feed("articles"), Reddit({AXIOS: ARTICLE}), job)
    article, refused = stored(AXIOS), stored(WSJ)
    assert discussion_url(article["url"], article["text"]) == AXIOS_POST  # from the line that closes its text
    assert discussion_url(refused["url"], refused["text"]) == WSJ_POST  # also when the article could not be read
    assert discussion_url(AMA_POST, "A post's own text.") == AMA_POST  # a post is its own discussion
    assert discussion_url("https://example.org/a", "Nothing to do with reddit.com/r/x at all.") == ""
    assert api.get(f"/api/articles/{article['id']}").json()["discussion_url"] == AXIOS_POST


def test_the_comments_under_a_post_are_summed_up_when_asked(api, job, monkeypatch):
    ctx = Reddit({AXIOS: ARTICLE})
    scrape(reddit_feed("articles"), ctx, job)
    article = stored(AXIOS)
    assert ctx.to("/comments/") == []  # the scrape itself read no comments
    sent = claude_sums_up(monkeypatch)
    monkeypatch.setattr(comments, "Context", lambda: ctx)

    done = wait_for(api, api.post(f"/api/articles/{article['id']}/comments").json()["job_id"])
    assert done["status"] == "done" and done["kind"] == "comments" and done["usage"]["calls"] == 1
    assert ctx.asked[-1] == (comments_url(AXIOS_POST, 50), False)  # one request to Reddit, for the top fifty
    read = api.get(f"/api/articles/{article['id']}").json()
    assert read["comments_summary"] == SUMMARY and read["comments_at"]
    listed = read["comments"]
    assert done["result"] == {"comments": 22, "post": AXIOS_POST} and len(listed) == 22
    assert listed[0]["author"] == "crab_races" and listed[0]["text"].startswith("Do you want to make Zelenskyy more popular")
    assert listed[1] == {"author": "BlueCollarLawyer", "text": "Trump is your enemy. Always was, always will be."}
    assert any("\n\n" in comment["text"] for comment in listed)  # a comment keeps its own paragraphs
    assert read["text"] == article["text"]  # the article itself is left as it was

    request = sent[0]
    assert request["model"] == "claude-haiku-5-5" and "never instructions" in request["system"]
    assert "do not judge who is right" in request["system"] and "numbers of votes are not known" in request["system"]
    assert request["prompt"].startswith("Post: Trump tells Ukraine to replace Zelensky over Russia fuel deal\n"
                                        "Posted in: r/geopolitics\n<post>\n")
    assert f'<comments count="{len(listed)}" order="highest voted first">\nu/crab_races: Do you want' in request["prompt"]
    assert "## Where they disagree" in request["prompt"] and "in English" in request["prompt"]
    assert request["schema"]["required"] == ["summary"]

    again = wait_for(api, api.post(f"/api/articles/{article['id']}/comments").json()["job_id"])  # a later look
    assert again["status"] == "done" and len(sent) == 2 and len(ctx.to("/comments/")) == 2
    about = api.get("/api/meta").json()["comments"]
    assert about["comments"] == 50 and about["model_label"] == "Claude Haiku 5.5" and 0 < about["usd"] < 0.01


def test_comments_that_are_not_there_or_cannot_be_read_cost_nothing(api, job, monkeypatch):
    class Quiet(Reddit):
        """Reddit when a post has no comments yet: its feed carries the post alone."""

        refuse = False

        def fetch(self, url, fetcher="http", **kwargs):
            if "/comments/" in url and "/.rss?" in url:
                if self.refuse:
                    raise FetchError("HTTP 429 for the comments", refused=True, status=429)
                return FetchResult(url, 200, "application/atom+xml", TEXT_ONLY.encode("utf-8"), "utf-8")
            return super().fetch(url, fetcher, **kwargs)

    ctx = Quiet({AXIOS: ARTICLE})
    scrape(reddit_feed("articles"), ctx, job)
    article = stored(AXIOS)
    plain = db.execute("INSERT INTO articles(source_id, url, title, text, fetched_at) VALUES(?, 'https://example.org/a',"
                       " 'A page', 'Plain text.', ?)", (article["source_id"], db.now())).lastrowid

    refused = api.post(f"/api/articles/{article['id']}/comments")  # there is no API key in the tests
    assert refused.status_code == 400 and "Anthropic API key" in refused.json()["detail"]
    sent = claude_sums_up(monkeypatch)
    monkeypatch.setattr(comments, "Context", lambda: ctx)
    assert api.post(f"/api/articles/{plain}/comments").status_code == 400  # not from Reddit
    assert api.post("/api/articles/99999/comments").status_code == 404

    none = wait_for(api, api.post(f"/api/articles/{article['id']}/comments").json()["job_id"])
    assert none["status"] == "error" and "no comments under this post" in none["error"]
    ctx.refuse = True
    later = wait_for(api, api.post(f"/api/articles/{article['id']}/comments").json()["job_id"])
    assert later["status"] == "error" and "could not be read from Reddit: HTTP 429" in later["error"]
    assert sent == [] and stored(AXIOS)["comments_summary"] == ""  # Claude was never asked
