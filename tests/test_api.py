"""The HTTP API, driven the way the dashboard drives it."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import config
from backend.ai import client as ai
from backend.main import app
from tests.test_plugins import LISTING_OPTIONS


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def wait_for(api: TestClient, job_id: str, seconds: float = 30) -> dict:
    deadline = time.time() + seconds
    while time.time() < deadline:
        job = api.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish: {job}")


def add_institute(api: TestClient, site: str, **extra) -> int:
    """Plug in the fake site through the same steps as the Add-source wizard."""
    started = api.post("/api/sources/analyze", json={"url": f"{site}/", "analyzer": "heuristic"})
    assert started.status_code == 200, started.text
    analysis = wait_for(api, started.json()["job_id"])
    assert analysis["status"] == "done", analysis
    recipe = analysis["result"]["recipe"]
    recipe["feeds"].append({
        "name": "Publications", "connector": "html_list", "url": f"{site}/publications", "content_type": "report",
        "options": {**LISTING_OPTIONS, "pagination": "next_link", "next_selector": "a.pager__next"},
    })
    created = api.post("/api/sources", json={"url": f"{site}/", "recipe": recipe, "analyzer": "heuristic", **extra})
    assert created.status_code == 200, created.text
    body = created.json()
    if body["job_id"]:
        assert wait_for(api, body["job_id"])["status"] == "done"
    return body["id"]


def test_meta_describes_the_plugins(api):
    meta = api.get("/api/meta").json()
    assert {c["name"] for c in meta["connectors"]} >= {"rss", "html_list", "sitemap", "reddit", "single"}
    html_list = next(c for c in meta["connectors"] if c["name"] == "html_list")
    assert {"key": "item_selector", "type": "text"}.items() <= html_list["fields"][0].items()
    assert [a["name"] for a in meta["analyzers"]] == ["heuristic", "claude"]
    assert meta["ai"] == {"available": False, "key_hint": ""}
    assert any(f["key"] == "pdf_link_selector" for f in meta["article_fields"])


def test_plug_in_a_source_and_read_it(api, site):
    source_id = add_institute(api, site)

    source = api.get(f"/api/sources/{source_id}").json()
    assert source["name"] == "Example Institute" and source["article_count"] == 9
    assert source["feed_counts"] == {"Example Institute News": 3, "Publications": 6}
    assert source["recipe"]["feeds"][1]["options"]["item_selector"] == "article.teaser"
    assert source["last_scraped_at"] and source["active_job"] is None

    listed = api.get("/api/sources").json()
    assert [s["name"] for s in listed] == ["Example Institute"]
    assert "recipe" not in listed[0] and len(listed[0]["feeds"]) == 2

    feed = api.get("/api/articles", params={"source_id": source_id, "limit": 5}).json()
    assert feed["total"] == 9 and len(feed["items"]) == 5
    assert "text" not in feed["items"][0]  # cards do not carry the full text
    article = api.get(f"/api/articles/{feed['items'][0]['id']}").json()
    assert article["text"] and article["source_name"] == "Example Institute"

    found = api.get("/api/articles", params={"q": "anduril drone", "sort": "relevance"}).json()
    assert [a["title"] for a in found["items"]] == ["Anduril and the new defence industrial base"]
    assert api.get("/api/stats").json()["articles"] == 9

    jobs = api.get("/api/jobs").json()
    assert [j["kind"] for j in jobs] == ["scrape", "analyze"]
    assert "logs" not in jobs[0]


def test_source_can_be_edited_rescraped_and_deleted(api, site):
    source_id = add_institute(api, site, scrape_now=False)
    assert api.get(f"/api/sources/{source_id}").json()["article_count"] == 0

    recipe = api.get(f"/api/sources/{source_id}").json()["recipe"]
    recipe["site_name"] = "Renamed Institute"
    recipe["feeds"][0]["enabled"] = False
    patched = api.patch(f"/api/sources/{source_id}",
                        json={"recipe": recipe, "interval_minutes": 120, "enrich_enabled": True}).json()
    assert patched["name"] == "Renamed Institute" and patched["interval_minutes"] == 120
    assert patched["enrich_enabled"] is True and "translate_enabled" not in patched

    job = wait_for(api, api.post(f"/api/sources/{source_id}/scrape", json={"deep": True}).json()["job_id"])
    assert job["status"] == "done" and job["result"]["new"] == 6
    # enrichment is on but cannot run; a scrape never translates
    assert any("AI summary + tags is on" in line["msg"] and "no API key" in line["msg"] for line in job["logs"])
    assert not any("Translat" in line["msg"] for line in job["logs"])
    detail = api.get(f"/api/sources/{source_id}").json()
    assert detail["translation"]["model_label"] == "Claude Haiku 5.5"
    assert detail["translation"]["waiting"] == {"items": 0, "usd": 0, "minutes": 0, "too_long": 0,
                                                "max_minutes": 20}  # the fake site is in English
    assert api.get("/api/meta").json()["translation"]["budget_usd"] == 0.5
    refused = api.post(f"/api/sources/{source_id}/translate")
    assert refused.status_code == 400 and "needs an Anthropic API key" in refused.json()["detail"]
    some_item = api.get("/api/articles", params={"source_id": source_id}).json()["items"][0]["id"]
    assert api.get(f"/api/articles/{some_item}").json()["translation"] is None  # in English: no button
    refused = api.post(f"/api/articles/{some_item}/translate")
    assert refused.status_code == 400 and "needs an Anthropic API key" in refused.json()["detail"]

    broken = {**recipe, "feeds": [{**recipe["feeds"][1], "connector": "nope"}]}
    rejected = api.patch(f"/api/sources/{source_id}", json={"recipe": broken})
    assert rejected.status_code == 400 and "unknown connector" in rejected.json()["detail"]

    assert api.delete(f"/api/sources/{source_id}").json() == {"deleted": True, "articles_removed": 6}
    assert api.get("/api/articles").json()["total"] == 0
    assert api.get(f"/api/sources/{source_id}").status_code == 404


def test_recipe_can_be_tested_before_saving(api, site):
    feed = {"name": "Publications", "connector": "html_list", "url": f"{site}/publications",
            "options": LISTING_OPTIONS}
    preview = api.post("/api/recipes/test-feed", json={"feed": feed}).json()
    assert preview["total_items"] == 2 and preview["items"][0]["title"].startswith("Drone swarms")

    bad = api.post("/api/recipes/test-feed", json={"feed": {**feed, "options": {"item_selector": "a["}}})
    assert bad.status_code == 400 and "not a valid CSS selector" in bad.json()["detail"]

    article = api.post("/api/recipes/test-article", json={"url": f"{site}/publications/p1",
                                                          "article": {"author_selector": ".byline"}}).json()
    assert article["author"] == "Jane Researcher" and article["pdf_url"].endswith("p1.pdf")


def test_failed_analysis_is_reported_on_the_job(api, site):
    started = api.post("/api/sources/analyze", json={"url": f"{site}/missing-page", "analyzer": "heuristic"})
    job = wait_for(api, started.json()["job_id"])
    assert job["status"] == "error" and "HTTP 404" in job["error"]

    assert api.post("/api/sources/analyze", json={"url": "not a url", "analyzer": "heuristic"}).status_code == 400
    no_key = api.post("/api/sources/analyze", json={"url": site, "analyzer": "claude"})
    assert no_key.status_code == 400 and "API key" in no_key.json()["detail"]


def test_topics_collect_matching_articles(api, site):
    source_id = add_institute(api, site)

    preview = api.post("/api/topics/preview", json={"name": "x", "terms": ["drone", "unmanned"]}).json()
    assert preview == {"matches": 3, "by_meaning": 0, "mentions": 0}

    topic = api.post("/api/topics", json={"name": "Anduril drones", "required_any": ["Anduril"],
                                          "terms": ["drone", " drone ", "autonomous"]}).json()
    assert topic["terms"] == ["drone", "autonomous"] and topic["matches"] == 1
    assert topic["sources"] == [{"id": source_id, "name": "Example Institute", "icon_url": f"{site}/icon.png",
                                 "matches": 1}]

    widened = api.patch(f"/api/topics/{topic['id']}", json={"required_any": [], "terms": ["drone", "unmanned"]}).json()
    assert widened["matches"] == 3
    articles = api.get(f"/api/topics/{topic['id']}/articles").json()
    assert articles["total"] == 3 and articles["items"][0]["snippet"]
    only_news = api.get(f"/api/topics/{topic['id']}/articles", params={"sort": "newest", "limit": 1}).json()
    assert only_news["items"][0]["title"].startswith("Institute opens new research programme")

    simple = api.post("/api/topics", json={"name": "Arctic"}).json()  # no terms: the name becomes the term
    assert simple["terms"] == ["Arctic"] and simple["matches"] == 1

    listed = api.get("/api/topics").json()
    assert [(t["name"], t["matches"]) for t in listed] == [("Anduril drones", 3), ("Arctic", 1)]
    assert api.patch(f"/api/topics/{simple['id']}", json={"terms": []}).status_code == 400
    assert api.post(f"/api/topics/{simple['id']}/briefing").status_code == 400  # no API key
    assert api.delete(f"/api/topics/{simple['id']}").json() == {"deleted": True}


def test_briefing_is_written_from_the_matching_articles(api, site, monkeypatch):
    add_institute(api, site)
    topic = api.post("/api/topics", json={"name": "Drones", "terms": ["drone", "unmanned"]}).json()
    seen = {}

    def fake_message(*, model, usage=None, stream=False, **request):
        seen.update(request, model=model, stream=stream)
        return SimpleNamespace(
            stop_reason="end_turn", stop_details=None,
            content=[SimpleNamespace(type="text", text="Drones matter [1]. Swarms too [2].\n\n## Gaps\nNone.")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0),
        )

    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "message", fake_message)
    job = wait_for(api, api.post(f"/api/topics/{topic['id']}/briefing").json()["job_id"])
    assert job["status"] == "done" and job["result"]["articles_read"] == 3

    prompt = seen["messages"][0]["content"]
    assert "[1] " in prompt and "[3] " in prompt and "Example Institute" in prompt and seen["stream"] is True
    stored = api.get(f"/api/topics/{topic['id']}").json()
    assert stored["briefing"].startswith("Drones matter [1]")
    assert [s["n"] for s in stored["briefing_sources"]] == [1, 2]  # only the cited ones are listed


def test_settings_roundtrip_and_validation(api):
    settings = api.get("/api/settings").json()
    assert settings["values"]["model_analyzer"] == "claude-opus-5-5"
    assert settings["values"]["model_enrich"] == "claude-haiku-5-5"

    saved = api.put("/api/settings", json={"values": {"request_delay_seconds": 2.5, "max_pages_first": "5"}}).json()
    assert saved["values"]["request_delay_seconds"] == 2.5 and saved["values"]["max_pages_first"] == 5
    assert config.get("max_pages_first") == 5

    for bad in ({"model_analyzer": "gpt-4"}, {"request_delay_seconds": -1}, {"no_such_setting": 1},
                {"user_agent": "  "}):
        assert api.put("/api/settings", json={"values": bad}).status_code == 400


def test_api_key_is_stored_but_never_returned(api, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    assert api.put("/api/settings/api-key", json={"key": "hunter2"}).status_code == 400
    status = api.put("/api/settings/api-key", json={"key": "sk-ant-api03-abcdefghijklmnop"}).json()
    assert status == {"available": True, "key_hint": "…mnop"}
    assert "sk-ant-api03-abcdefghijklmnop" in env_file.read_text()
    assert "sk-ant" not in api.get("/api/settings").text and "sk-ant" not in api.get("/api/meta").text


def test_unknown_things_are_404(api):
    for path in ("/api/sources/999", "/api/articles/999", "/api/topics/999", "/api/jobs/nope", "/api/nothing"):
        assert api.get(path).status_code == 404
    assert api.get("/anything/else").status_code == 200  # the dashboard (or its 'not built' notice)
