"""The Claude calls, through the real Anthropic SDK, against a fake HTTP server.

No key and no network: a mock transport plays the API. This checks what the mocks in the other tests
cannot: that the SDK accepts every parameter the platform sends, what actually goes over the wire, and
that replies parsed by the SDK can be sent back as conversation history.
"""

from __future__ import annotations

import json

import anthropic
import httpx2
import pytest

from backend import config, db
from backend.ai import client as ai
from backend.analyzers import analyzers
from backend.connectors import Context
from backend.pipeline.enrich import enrich_article
from backend.pipeline.scrape import store_article
from backend.schemas import Recipe
from backend.search.expand import expand_topic
from tests.test_analyzers import good_feed, recipe_payload
from tests.test_pipeline import add_source

USAGE = {"input_tokens": 1200, "output_tokens": 80, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def api_message(content: list[dict], stop_reason: str, model: str = "claude-opus-5-5") -> dict:
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model, "content": content,
            "stop_reason": stop_reason, "stop_sequence": None, "usage": USAGE}


def sse(events: list[dict]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class FakeApi:
    """Answers POST /v1/messages with scripted bodies and keeps the requests it received."""

    def __init__(self, replies: list):
        self.replies = list(replies)
        self.requests: list[httpx2.Request] = []
        self.bodies: list[dict] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content))
        reply = self.replies.pop(0)
        if isinstance(reply, bytes):
            return httpx2.Response(200, content=reply, headers={"content-type": "text/event-stream"})
        return httpx2.Response(200, json=reply)


@pytest.fixture
def fake_api(monkeypatch):
    def install(replies: list) -> FakeApi:
        api = FakeApi(replies)
        sdk = anthropic.Anthropic(
            api_key="sk-ant-test-key", max_retries=0,
            http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(api)),
        )
        monkeypatch.setattr(ai, "client", lambda: sdk)
        monkeypatch.setattr(ai, "available", lambda: True)
        return api
    return install


def test_source_analysis_speaks_valid_messages_api(site, job, fake_api):
    api = fake_api([
        api_message([
            {"type": "thinking", "thinking": "", "signature": "sig-1"},
            {"type": "text", "text": "Checking the publications listing."},
            {"type": "tool_use", "id": "toolu_1", "name": "test_feed", "input": {"feed": good_feed(site), "pages": 2}},
        ], "tool_use"),
        api_message([
            {"type": "tool_use", "id": "toolu_2", "name": "submit_recipe",
             "input": recipe_payload(site, [good_feed(site)])},
        ], "tool_use"),
    ])

    analysis = analyzers.get("claude").analyze(f"{site}/", "reports only", job, Context())
    assert analysis.recipe.feeds[0].connector == "html_list"
    assert analysis.usage["calls"] == 2 and analysis.usage["input_tokens"] == 2400

    first, second = api.bodies
    request = api.requests[0]
    assert request.url.path == "/v1/messages"
    assert "server-side-fallback-2026-07-01" in request.headers["anthropic-beta"]
    assert request.headers["x-api-key"] == "sk-ant-test-key"

    assert first["model"] == "claude-opus-5-5" and first["max_tokens"] == 16000
    assert first["fallbacks"] == "default"
    assert first["thinking"] == {"type": "adaptive"}
    assert first["output_config"] == {"effort": "high"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert "stream" not in first or first["stream"] is False
    assert "tool_choice" not in first and "temperature" not in first  # both are rejected by Claude Opus 5.5
    assert [t["name"] for t in first["tools"]] == ["fetch_page", "test_feed", "test_article", "submit_recipe"]
    assert first["system"].startswith("You set up new sources")
    assert first["messages"][0]["role"] == "user" and "reports only" in first["messages"][0]["content"]

    # second request: the assistant turn is replayed exactly as it was received, thinking block included,
    # followed by one user message that answers the tool call
    history = second["messages"]
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-1"}
    assert history[1]["content"][2]["type"] == "tool_use" and history[1]["content"][2]["id"] == "toolu_1"
    (result,) = history[2]["content"]
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert json.loads(result["content"])["total_items"] == 4
    assert second["system"] == first["system"] and second["tools"] == first["tools"]  # a stable, cacheable prefix


def test_structured_requests_ask_for_json_and_skip_fallback_on_haiku(fake_api):
    answer = {"description": "Unmanned aircraft.", "required_any": [], "terms": ["drone", "UAV", "drone"]}
    api = fake_api([api_message([{"type": "text", "text": json.dumps(answer)}], "end_turn")])
    usage = ai.Usage()
    assert expand_topic("Drones", usage) == {"description": "Unmanned aircraft.", "required_any": [],
                                             "terms": ["drone", "UAV"]}
    body = api.bodies[0]
    assert body["output_config"]["effort"] == "low"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert body["fallbacks"] == "default" and usage.calls == 1

    labels = {"summary": "s", "tags": ["a"], "language": "en"}
    api = fake_api([api_message([{"type": "text", "text": json.dumps(labels)}], "end_turn", "claude-haiku-5-5")])
    ai.structured(model="claude-haiku-5-5", system="s", prompt="p", schema={"type": "object"}, task="label")
    assert "fallbacks" not in api.bodies[0]  # Claude Haiku 5.5 has no server-side fallback
    assert "anthropic-beta" not in api.requests[0].headers


def test_article_summaries_are_written_in_the_chosen_language(fake_api):
    source_id = add_source(Recipe(site_name="SWP", homepage="https://example.org", language="de"))
    article_id = store_article(source_id, "Publications", {
        "url": "https://example.org/anti-schiffs-waffen", "title": "Die unterschätzte Bedrohung", "author": "",
        "published_at": "", "summary": "", "text": "Landgestützte Anti-Schiffs-Waffen verändern die Seekriegführung.",
        "image_url": "", "pdf_url": "", "content_type": "report", "language": "de", "tags": "Sicherheitspolitik",
        "word_count": 5, "is_partial": False,
    })
    labels = {"summary": "Land-based anti-ship weapons are changing naval warfare.",
              "tags": ["Anti-Ship Missiles", "naval warfare"], "language": "de"}
    reply = api_message([{"type": "text", "text": json.dumps(labels)}], "end_turn", "claude-haiku-5-5")
    api = fake_api([reply, reply])
    usage = ai.Usage()

    assert enrich_article(article_id, usage)
    body = api.bodies[0]
    english = "in English, also when the article is in another language."
    assert body["model"] == "claude-haiku-5-5"
    assert body["output_config"]["format"]["schema"]["properties"]["summary"]["description"].endswith(english)
    assert body["messages"][0]["content"].endswith(f"Write the summary {english}")
    stored = db.row("SELECT ai_summary, tags, language FROM articles WHERE id = ?", (article_id,))
    assert stored["ai_summary"] == labels["summary"] and stored["language"] == "de"
    assert stored["tags"] == "Sicherheitspolitik, anti-ship missiles, naval warfare"
    assert usage.cost_usd == pytest.approx((1200 * 0.10 + 80 * 0.50) / 1_000_000)  # Claude Haiku 5.5 prices

    config.update({"summary_language": config.ARTICLE_LANGUAGE})
    assert enrich_article(article_id, usage)
    assert api.bodies[1]["messages"][0]["content"].endswith("Write the summary in the language of the article.")
    with pytest.raises(ValueError):
        config.update({"summary_language": "Klingon"})


def test_long_answers_are_streamed_and_assembled(fake_api):
    start = api_message([], None)
    api = fake_api([sse([
        {"type": "message_start", "message": start},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Drones matter [1]. "}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Swarms too [2]."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
         "usage": {"output_tokens": 42}},
        {"type": "message_stop"},
    ])])
    usage = ai.Usage()
    reply = ai.message(model="claude-opus-5-5", usage=usage, stream=True, max_tokens=16000,
                       thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                       messages=[{"role": "user", "content": "Brief me."}])
    assert ai.text_of(reply) == "Drones matter [1]. Swarms too [2]."
    assert reply.stop_reason == "end_turn" and usage.output_tokens == 42
    assert api.bodies[0]["stream"] is True and api.bodies[0]["fallbacks"] == "default"


def test_api_failures_become_readable_messages(fake_api, monkeypatch):
    def failing(status: int, kind: str):
        def handler(request):
            return httpx2.Response(status, json={"type": "error", "error": {"type": kind, "message": "nope"}})
        sdk = anthropic.Anthropic(api_key="sk-ant-bad", max_retries=0,
                                  http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
        monkeypatch.setattr(ai, "client", lambda: sdk)

    for status, kind, expected in [
        (401, "authentication_error", "API key was rejected"),
        (404, "not_found_error", "was not found"),
        (429, "rate_limit_error", "rate limit"),
        (400, "invalid_request_error", "rejected the request: nope"),
        (529, "overloaded_error", "Claude API error 529: nope"),
    ]:
        failing(status, kind)
        with pytest.raises(ai.AIError, match=expected):
            ai.message(model="claude-haiku-5-5", max_tokens=10, messages=[{"role": "user", "content": "hi"}])
