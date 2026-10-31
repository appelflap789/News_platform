"""The analyzers. Claude itself is replaced by a script of replies, so the agent loop is tested offline:
what it sends to the API, how it runs tools, and how it handles mistakes."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.ai import client as ai
from backend.analyzers import analyzers
from backend.analyzers._digest import describe
from backend.analyzers._prescan import prescan
from backend.analyzers.claude_agent import MAX_TURNS, feed_schema, system_prompt, tool_definitions
from backend.connectors import Context
from backend.fetchers import fetchers
from backend.schemas import Recipe, validate_recipe
from tests.test_plugins import LISTING_OPTIONS


# --- digest and pre-scan ---------------------------------------------------------------------

def test_digest_keeps_structure_and_drops_noise(site):
    digest = describe(fetchers.get("http").fetch(f"{site}/publications"))
    assert "Title: Publications | Example Institute" in digest
    assert "Navigation links:" in digest and "Publications -> /publications" in digest
    assert "/publications/… ×" in digest  # the link-path overview points at the item URL pattern
    assert "article class=\"teaser\"" in digest and "teaser__link" in digest
    assert "window.tracking" not in digest and "<script" not in digest


def test_digest_collapses_repeated_siblings():
    from backend.fetchers import FetchResult

    cards = "".join(f"<li class='card'><a href='/x/{n}'>Item {n}</a></li>" for n in range(30))
    html = f"<html><head><title>T</title></head><body><ul>{cards}</ul><p>{'text ' * 100}</p></body></html>"
    digest = describe(FetchResult("https://e.org/", 200, "text/html", html.encode()))
    assert digest.count("<li class=\"card\">") == 3
    assert "<!-- +27 more li.card elements like the ones above -->" in digest
    zoomed = describe(FetchResult("https://e.org/", 200, "text/html", html.encode()), selector="li.card")
    assert "30 element(s) match" in zoomed


def test_digest_warns_about_javascript_pages_and_cuts_long_ones(site):
    assert "probably rendered with JavaScript" in describe(fetchers.get("http").fetch(f"{site}/js-only"))
    cut = describe(fetchers.get("http").fetch(f"{site}/publications"), max_chars=300)
    assert "Outline cut at 300" in cut and "selector" in cut


def test_digest_summarises_feeds_sitemaps_and_pdfs(site):
    fetch = fetchers.get("http").fetch
    feed = describe(fetch(f"{site}/feed.xml"))
    assert 'RSS/Atom feed "Example Institute News" with 3 entries' in feed and "2026-10-05" in feed
    assert "Sitemap with 11 URLs" in describe(fetch(f"{site}/sitemap.xml"))
    assert "PDF document, 1 pages" in describe(fetch(f"{site}/files/p1.pdf"))


def test_prescan_finds_feeds_and_sitemaps(site):
    scan = prescan(f"{site}/", Context())
    assert scan.kind == "html" and scan.site_name == "Example Institute"
    assert [f["url"] for f in scan.feeds] == [f"{site}/feed.xml"]
    assert scan.feeds[0]["entries"] == 3 and not scan.feeds[0]["full_content"]
    assert scan.sitemaps == [f"{site}/sitemap.xml"]
    assert scan.icon_url == f"{site}/icon.png"
    as_feed = prescan(f"{site}/feed.xml", Context())
    assert as_feed.kind == "feed" and as_feed.site_name == "Example Institute News"
    assert prescan(f"{site}/files/p1.pdf", Context()).kind == "pdf"
    assert prescan("https://www.reddit.com/r/drones", Context()).kind == "reddit"  # decided without a request


# --- heuristic analyzer ----------------------------------------------------------------------

def test_quick_detect_builds_a_working_recipe(site, job):
    analysis = analyzers.get("heuristic").analyze(f"{site}/", "", job, Context())
    recipe = analysis.recipe
    validate_recipe(recipe)
    assert recipe.site_name == "Example Institute" and recipe.language == "en"
    assert [(f.connector, f.url) for f in recipe.feeds] == [("rss", f"{site}/feed.xml")]
    assert analysis.previews["Example Institute News"]["total_items"] == 3
    assert "Found **1 feed(s)**" in recipe.structure_report


def test_quick_detect_handles_reddit_and_documents(site, job):
    reddit = analyzers.get("heuristic").analyze("https://www.reddit.com/r/drones/top", "", job, FailingContext())
    assert [(feed.connector, feed.content_type) for feed in reddit.recipe.feeds] == [("reddit", "article"),
                                                                                     ("reddit", "post")]
    assert reddit.recipe.site_name == "r/drones"
    # sampling failed (no network here) but the recipe is still returned
    assert "error" in reddit.previews["Shared articles"] and "error" in reddit.previews["Posts and comments"]

    document = analyzers.get("heuristic").analyze(f"{site}/files/p1.pdf", "", job, Context())
    assert document.recipe.feeds[0].connector == "single"
    assert document.previews["Document"]["total_items"] == 1


class FailingContext(Context):
    def fetch(self, url, fetcher="http", **kwargs):
        from backend.fetchers import FetchError

        raise FetchError("offline in tests")


# --- Claude analyzer, with scripted replies -----------------------------------------------------

def tool_use(call_id: str, name: str, payload: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=call_id, name=name, input=payload)


def reply(*blocks, stop_reason: str = "tool_use") -> SimpleNamespace:
    return SimpleNamespace(
        content=list(blocks), stop_reason=stop_reason, stop_details=None,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
    )


class ScriptedClaude:
    """Replaces ai.message: returns the next scripted reply and records every request."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def __call__(self, *, model, usage=None, stream=False, **request):
        # snapshot: the analyzer keeps appending to the same list
        self.requests.append({**request, "model": model, "messages": list(request["messages"])})
        if not self.replies:
            raise AssertionError("The analyzer asked Claude for more replies than the test scripted")
        next_reply = self.replies.pop(0)
        if usage is not None:
            usage.add(model, next_reply.usage)
        return next_reply

    def results_after(self, turn: int) -> list[dict]:
        """The tool results the analyzer sent back after reply number `turn` (0-based)."""
        return self.requests[turn + 1]["messages"][-1]["content"]


@pytest.fixture
def claude(monkeypatch):
    def install(replies: list) -> ScriptedClaude:
        scripted = ScriptedClaude(replies)
        monkeypatch.setattr(ai, "message", scripted)
        monkeypatch.setattr(ai, "client", lambda: object())
        monkeypatch.setattr(ai, "available", lambda: True)
        return scripted
    return install


def good_feed(site: str) -> dict:
    return {"name": "Publications", "connector": "html_list", "url": f"{site}/publications",
            "content_type": "report", "fetch_detail": True,
            "options": {**LISTING_OPTIONS, "pagination": "page_param", "page_param": "page", "page_start": 0}}


def recipe_payload(site: str, feeds: list[dict]) -> dict:
    return {"site_name": "Example Institute", "homepage": f"{site}/", "description": "A think tank.",
            "language": "en", "feeds": feeds, "article": {"author_selector": ".byline"},
            "structure_report": "## Structure\nPublications are listed at /publications, two per page."}


def test_claude_analyzer_runs_tools_and_returns_a_tested_recipe(site, job, claude):
    bad_feed = {**good_feed(site), "options": {"item_selector": "article["}}
    scripted = claude([
        reply(SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Looking at the listing."),
              tool_use("t1", "fetch_page", {"url": f"{site}/publications"})),
        reply(tool_use("t2", "test_feed", {"feed": bad_feed}),
              tool_use("t3", "fetch_page", {"url": "https://evil.example.com/steal"})),
        reply(tool_use("t4", "submit_recipe", recipe_payload(site, [good_feed(site)]))),  # not tested yet
        reply(tool_use("t5", "test_feed", {"feed": good_feed(site), "pages": 2}),
              tool_use("t6", "test_article", {"url": f"{site}/publications/p1", "article": {"author_selector": ".byline"}})),
        reply(tool_use("t7", "submit_recipe", recipe_payload(site, [good_feed(site)]))),
    ])

    analysis = analyzers.get("claude").analyze(f"{site}/", "only the reports", job, Context())

    # the recipe that comes back is the one Claude submitted, completed from the pre-scan
    recipe = analysis.recipe
    validate_recipe(recipe)
    assert recipe.site_name == "Example Institute" and recipe.icon_url == f"{site}/icon.png"
    assert recipe.feeds[0].options["page_start"] == "0" and recipe.article == {"author_selector": ".byline"}
    assert analysis.previews["Publications"]["total_items"] == 4  # the tested result is reused, not re-fetched
    assert analysis.usage["calls"] == 5 and analysis.usage["estimated_cost_usd"] > 0

    # request 1: what Claude is given to start with
    first = scripted.requests[0]
    assert first["system"] == system_prompt() and first["tools"] == tool_definitions()
    assert first["thinking"] == {"type": "adaptive"} and first["output_config"] == {"effort": "high"}
    opening = first["messages"][0]["content"]
    assert "only the reports" in opening and f"{site}/feed.xml" in opening and "Digest of the start page" in opening

    # turn 1: the page digest goes back as the tool result, and the assistant turn is replayed unchanged
    assert scripted.requests[1]["messages"][1]["content"][0].type == "thinking"
    (digest,) = scripted.results_after(0)
    assert digest["tool_use_id"] == "t1" and "teaser__link" in digest["content"] and "is_error" not in digest

    # turn 2: both calls answered in ONE message; a bad selector and an off-site URL come back as errors
    selector_error, offsite = scripted.results_after(1)
    assert selector_error["tool_use_id"] == "t2" and selector_error["is_error"]
    assert "not a valid CSS selector" in selector_error["content"]
    assert offsite["is_error"] and "outside the source's site" in offsite["content"]

    # turn 3: an untested recipe is pushed back once
    (pushback,) = scripted.results_after(2)
    assert pushback["is_error"] and "was not tested" in pushback["content"]

    # turn 4: test results are JSON the model can read
    feed_result, article_result = scripted.results_after(3)
    tested = json.loads(feed_result["content"])
    assert tested["total_items"] == 4 and tested["pages"][1]["url"].endswith("page=1")
    assert json.loads(article_result["content"])["author"] == "Jane Researcher"

    assert "Tested feed “Publications”" in job.text() and "Claude: Looking at the listing." in job.text()


def test_claude_analyzer_accepts_a_resubmitted_recipe_and_an_empty_one(site, job, claude):
    untested = recipe_payload(site, [good_feed(site)])
    claude([reply(tool_use("a", "submit_recipe", untested)), reply(tool_use("b", "submit_recipe", untested))])
    analysis = analyzers.get("claude").analyze(f"{site}/", "", job, Context())
    assert analysis.previews["Publications"]["total_items"] == 2  # sampled afterwards for the review screen

    claude([reply(tool_use("c", "submit_recipe", recipe_payload(site, [])))])
    nothing = analyzers.get("claude").analyze(f"{site}/js-only", "", job, Context())
    assert nothing.recipe.feeds == [] and nothing.previews == {}


def test_claude_analyzer_feeds_validation_errors_back(site, job, claude):
    wrong = recipe_payload(site, [{**good_feed(site), "connector": "telepathy"}])
    scripted = claude([reply(tool_use("a", "submit_recipe", wrong)),
                       reply(tool_use("b", "submit_recipe", recipe_payload(site, [])))])
    analyzers.get("claude").analyze(f"{site}/", "", job, Context())
    (error,) = scripted.results_after(0)
    assert error["is_error"] and "unknown connector 'telepathy'" in error["content"]


def test_claude_analyzer_nudges_then_gives_up_when_no_recipe_comes(site, job, claude):
    idle = reply(SimpleNamespace(type="text", text="I think I am done."), stop_reason="end_turn")
    scripted = claude([idle, idle, idle])
    with pytest.raises(ai.AIError, match="without submitting a recipe"):
        analyzers.get("claude").analyze(f"{site}/", "", job, Context())
    assert "submit_recipe" in scripted.requests[1]["messages"][-1]["content"]


def test_claude_analyzer_discards_truncated_replies(site, job, claude):
    cut_off = reply(tool_use("x", "test_feed", {"feed": {"name": "half"}}), stop_reason="max_tokens")
    scripted = claude([cut_off, reply(tool_use("b", "submit_recipe", recipe_payload(site, [])))])
    analyzers.get("claude").analyze(f"{site}/", "", job, Context())
    retry = scripted.requests[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "user"]  # the incomplete tool call never entered the history
    assert "hit the output limit" in retry[-1]["content"]


def test_claude_analyzer_reports_refusals_and_step_limit(site, job, claude):
    refused = reply(stop_reason="refusal")
    refused.stop_details = SimpleNamespace(category="cyber")
    claude([refused])
    with pytest.raises(ai.AIError, match="declined.*cyber"):
        analyzers.get("claude").analyze(f"{site}/", "", job, Context())

    looping = [reply(tool_use(f"t{n}", "test_article", {"url": f"{site}/news/a1"})) for n in range(MAX_TURNS)]
    scripted = claude(looping)
    with pytest.raises(ai.AIError, match=f"within {MAX_TURNS} steps"):
        analyzers.get("claude").analyze(f"{site}/", "", job, Context())
    warning = scripted.requests[MAX_TURNS - 3]["messages"][-1]["content"][-1]
    assert warning["type"] == "text" and "three steps left" in warning["text"]


def test_claude_analyzer_needs_a_key(site, job):
    with pytest.raises(ai.AIError, match="No Anthropic API key"):
        analyzers.get("claude").analyze(f"{site}/", "", job, Context())


def test_tool_schema_follows_the_connector_registry():
    schema = feed_schema()
    assert schema["properties"]["connector"]["enum"] == ["html_list", "rss", "reddit", "single", "sitemap"]
    options = schema["properties"]["options"]["properties"]
    assert options["pagination"]["description"].startswith("[html_list, rss]")
    assert options["page_start"]["type"] == "integer" and options["url_pattern"]["description"].startswith("[sitemap]")
    Recipe.model_validate({"site_name": "x", "feeds": []})


def test_message_uses_refusal_fallback_only_where_supported(monkeypatch):
    """ai.message picks the endpoint and parameters per model."""
    calls = []

    class Endpoint:
        def __init__(self, name):
            self.name = name

        def create(self, **request):
            calls.append((self.name, request))
            return reply(SimpleNamespace(type="text", text="ok"), stop_reason="end_turn")

    fake = SimpleNamespace(messages=Endpoint("stable"), beta=SimpleNamespace(messages=Endpoint("beta")))
    monkeypatch.setattr(ai, "client", lambda: fake)

    ai.message(model="claude-opus-5-5", max_tokens=10, messages=[])
    ai.message(model="claude-haiku-5-5", max_tokens=10, messages=[])
    assert calls[0][0] == "beta" and calls[0][1]["fallbacks"] == "default"
    assert calls[0][1]["betas"] == ["server-side-fallback-2026-07-01"]
    assert calls[1][0] == "stable" and "fallbacks" not in calls[1][1]

    from backend import config
    config.update({"refusal_fallback": False})
    ai.message(model="claude-opus-5-5", max_tokens=10, messages=[])
    assert calls[2][0] == "stable"


def test_usage_adds_up_cost():
    usage = ai.Usage()
    usage.add("claude-opus-5-5", SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000,
                                                 cache_read_input_tokens=0, cache_creation_input_tokens=0))
    assert usage.as_dict()["estimated_cost_usd"] == 6.0  # $4 input + $2 output
