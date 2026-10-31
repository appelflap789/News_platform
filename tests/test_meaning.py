"""Embeddings, search by meaning, and the topic page: what belongs to a topic, its timeline and trend, and the
two texts Claude writes on it.

The embeddings here come from the stand-in model (it counts words, see search/embed.py), so "close in meaning"
in these tests means "shares words". What is tested is the machinery around it.
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import config, db
from backend.ai import briefing
from backend.ai import client as ai
from backend.main import app
from backend.pipeline.scrape import scrape_source, store_article
from backend.schemas import Recipe
from backend.search import embed, meaning, query
from backend.search import topics as topic_search
from tests.test_pipeline import add_source, institute


@pytest.fixture(autouse=True)
def by_meaning():
    config.update({"meaning_enabled": True})


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def store(title: str, summary: str = "", *, published: str = "", source: str = "Example Institute",
          kind: str = "article", fetched: str = "") -> int:
    found = db.row("SELECT id FROM sources WHERE name = ?", (source,))
    source_id = found["id"] if found else add_source(Recipe(site_name=source, homepage="https://example.org"))
    article_id = store_article(source_id, "Feed", {
        "url": f"https://example.org/{source}/{abs(hash((title, summary, published)))}", "title": title, "author": "",
        "published_at": published, "summary": summary, "text": f"{summary} Further text of the item.",
        "image_url": "", "pdf_url": "", "content_type": kind, "language": "en", "tags": "",
        "word_count": 40, "is_partial": False,
    })
    if fetched:
        db.execute("UPDATE articles SET fetched_at = ? WHERE id = ?", (fetched, article_id))
    return article_id


def topic(**fields) -> dict:
    return {"name": "x", "description": "", "required_any": [], "terms": [], "by_meaning": True,
            "reach": "balanced", **fields}


def wait_for(api: TestClient, job_id: str) -> dict:
    deadline = time.time() + 30
    while time.time() < deadline:
        job = api.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def claude_says(monkeypatch, text: str) -> list[dict]:
    """Make every Claude request answer `text`; returns the list the requests are collected in."""
    sent: list[dict] = []

    def fake_message(*, model, usage=None, stream=False, **request):
        sent.append({**request, "model": model, "stream": stream})
        reply = SimpleNamespace(
            stop_reason="end_turn", stop_details=None, content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_read_input_tokens=0,
                                  cache_creation_input_tokens=0))
        if usage is not None:
            usage.add(model, reply.usage)
        return reply

    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "message", fake_message)
    return sent


# --- embeddings ----------------------------------------------------------------------------

def test_a_scrape_ends_by_embedding_what_it_stored(site, job):
    totals = scrape_source(add_source(institute(site)), job, deep=True)
    assert totals["new"] == 9 and totals["embedded"] == 9
    assert embed.pending() == 0 and len(embed.index()) == 9
    assert embed.status() == {"enabled": True, "available": True, "reason": "", "model": "hash-256", "items": 9,
                              "embedded": 9, "pending": 0}


def test_an_embedding_follows_the_title_and_summary_and_goes_with_its_item():
    article_id = store("Drone swarms over the Baltic", "Small states buy drone swarms.")
    other = store("Wind turbines in the North Sea", "A new wind farm opens.")
    assert embed.embed_pending() == {"embedded": 2}
    before = embed.index().vectors([article_id])[0].copy()

    db.execute("UPDATE articles SET word_count = 5 WHERE id = ?", (article_id,))  # not what an embedding is made of
    assert embed.pending() == 0
    db.execute("UPDATE articles SET ai_summary = ? WHERE id = ?", ("Navies test unmanned boats.", article_id))
    assert embed.pending() == 1 and len(embed.index()) == 1  # dropped at once; the matrix in memory follows
    assert embed.embed_pending() == {"embedded": 1}
    assert not (embed.index().vectors([article_id])[0] == before).all()  # made from Claude's summary now

    db.execute("DELETE FROM articles WHERE id = ?", (other,))
    assert db.scalar("SELECT COUNT(*) FROM embeddings") == 1 and len(embed.index()) == 1


def test_what_is_embedded_is_the_title_and_a_summary_not_the_boilerplate():
    shared = "A tanker was attacked. Shared in r/energy by u/someone: https://www.reddit.com/r/energy/comments/1/x/"
    article = {"title": "Tanker attacked", "summary": shared, "ai_summary": "", "text": "© 2026 All rights reserved."}
    assert embed.text_for(article) == "Tanker attacked. A tanker was attacked."
    article["ai_summary"] = "Claude's summary."
    assert embed.text_for(article) == "Tanker attacked. Claude's summary."


def test_switched_off_or_not_installed_nothing_is_found_by_meaning_and_nothing_breaks(site, job, monkeypatch):
    config.update({"meaning_enabled": False})
    totals = scrape_source(add_source(institute(site)), job, deep=True)
    assert "embedded" not in totals and embed.ready() is False
    assert "switched off" in embed.status()["reason"]
    assert meaning.search("drone")["total"] == 2  # the search by words, as before

    config.update({"meaning_enabled": True})
    monkeypatch.setattr(embed, "np", None)
    assert "not installed" in embed.missing() and embed.status()["available"] is False
    assert meaning.search("drone")["total"] == 2
    assert len(topic_search.members(topic(terms=["drone"])).ids) == 2


def test_a_model_that_cannot_be_loaded_is_reported_and_the_scrape_still_succeeds(site, job, monkeypatch):
    def broken(self):
        raise OSError("no internet")

    monkeypatch.setattr(embed.HashModel, "__init__", broken)
    monkeypatch.setattr(embed, "_model", None)
    totals = scrape_source(add_source(institute(site)), job, deep=True)
    assert totals["new"] == 9 and "embedded" not in totals
    assert "could not be loaded" in job.text() and "no internet" in embed.status()["reason"]


# --- search --------------------------------------------------------------------------------

def test_search_also_finds_what_is_about_the_same_thing_in_other_words(site, job):
    scrape_source(add_source(institute(site)), job, deep=True)
    words_only = query.search(query.text_match("drone swarms defence tactics"))
    assert words_only["total"] == 0  # no item contains all four words

    found = meaning.search("drone swarms defence tactics")
    assert found["items"][0]["title"] == "Drone swarms and the future of air defence"
    assert found["items"][0]["found_by"] == "meaning"

    both = meaning.search("drone")
    assert both["total"] >= 2 and both["items"][0]["found_by"] == "words" and both["items"][0]["snippet"]
    assert meaning.search("zebra crossing")["total"] == 0
    assert all(item["content_type"] == "news" for item in meaning.search("drone systems", content_type="news")["items"])


def test_the_reader_is_given_items_about_the_same_thing(api):
    first = store("Drone swarms over the Baltic", "Small states buy drone swarms for air defence.")
    second = store("Baltic states order drone swarms", "Drone swarms for air defence are bought by small states.")
    store("Wind turbines in the North Sea", "A new wind farm opens off the coast.")
    assert api.get(f"/api/articles/{first}/similar").json() == {"items": []}  # nothing is embedded yet
    embed.embed_pending()
    close = api.get(f"/api/articles/{first}/similar").json()["items"]
    assert [item["id"] for item in close] == [second] and close[0]["similarity"] > 0.6
    assert api.get("/api/articles/99999/similar").status_code == 404


# --- what belongs to a topic ---------------------------------------------------------------

@pytest.fixture
def library() -> dict:
    ids = {
        "swarm": store("Drone swarms and the future of air defence", "Drone swarms change air defence for small states."),
        "anduril": store("Anduril builds drone swarms", "Anduril sells drone swarms for air defence to the navy."),
        "boats": store("Unmanned boats for the navy", "The navy tests unmanned boats in the harbour."),
        "wind": store("Wind turbines in the North Sea", "A new wind farm opens off the coast."),
    }
    embed.embed_pending()
    return ids


def test_a_topic_collects_by_its_words_and_by_its_meaning(library):
    words = topic_search.members(topic(name="Navy", terms=["navy"], by_meaning=False))
    assert set(words.ids) == {library["anduril"], library["boats"]} and set(words.why.values()) == {"words"}

    # No item contains the term, but two are about what the name says.
    found = topic_search.members(topic(name="Drone swarms air defence", terms=["zebra"]))
    assert set(found.ids) == {library["swarm"], library["anduril"]}
    assert set(found.why.values()) == {"meaning"} and found.score[found.ids[0]] > 0.6

    # Two items say "navy". One is about drone swarms as well; the other is about boats and only shares the word.
    both = topic_search.members(topic(name="Drone swarms air defence", terms=["navy"]))
    assert both.why == {library["swarm"]: "meaning", library["anduril"]: "words", library["boats"]: "mention"}
    assert set(both.ids) == {library["swarm"], library["anduril"]} and both.mentions == [library["boats"]]
    assert both.scope("all") == both.ids + both.mentions


def test_a_topic_about_one_name_only_collects_items_that_mention_it(library):
    found = topic_search.members(topic(name="Drone swarms air defence", required_any=["Anduril"], terms=["zebra"]))
    assert found.ids == [library["anduril"]] and found.why[library["anduril"]] == "meaning"


def test_an_item_that_only_mentions_a_topic_is_set_aside(api, library):
    passing = store("Diesel prices rise again", "Truckers and farmers pay more for diesel at the pump this week "
                    "because refineries cut their output, and a drone was seen.")
    embed.embed_pending()
    created = api.post("/api/topics", json={"name": "Drone swarms air defence", "terms": ["drone"]}).json()
    assert created["matches"] == 2 and created["mentions"] == 1  # it says "drone" once and is about diesel
    about = api.get(f"/api/topics/{created['id']}/articles").json()
    assert {item["id"] for item in about["items"]} == {library["swarm"], library["anduril"]}
    mentions = api.get(f"/api/topics/{created['id']}/articles", params={"scope": "mentions"}).json()
    assert [(item["id"], item["why"]) for item in mentions["items"]] == [(passing, "mention")]
    assert mentions["items"][0]["snippet"]
    assert api.get(f"/api/topics/{created['id']}/articles", params={"scope": "all"}).json()["total"] == 3
    assert api.get(f"/api/topics/{created['id']}/timeline").json()["total"] == 2  # the page is made from what it is about

    # You know better: "belongs here" brings it in. And a topic that goes by words alone sets nothing aside.
    api.post(f"/api/topics/{created['id']}/items", json={"article_id": passing, "verdict": "in"})
    assert api.get(f"/api/topics/{created['id']}").json()["mentions"] == 0
    words = api.patch(f"/api/topics/{created['id']}", json={"by_meaning": False}).json()
    assert (words["matches"], words["mentions"]) == (3, 0)


def test_reach_decides_how_close_an_item_has_to_be(library, monkeypatch):
    monkeypatch.setattr(topic_search, "REACH", {"narrow": 0.95, "balanced": 0.6, "broad": 0.05})
    count = lambda reach: len(topic_search.members(topic(name="Drone swarms air defence navy", reach=reach)).ids)
    assert (count("narrow"), count("balanced"), count("broad")) == (0, 2, 3)


def test_what_you_say_about_an_item_decides_and_teaches_the_topic(api, library):
    created = api.post("/api/topics", json={"name": "Drone swarms air defence", "terms": ["zebra"]}).json()
    assert created["matches"] == 2 and created["by"] == {"words": 0, "meaning": 2, "you": 0}

    said = api.post(f"/api/topics/{created['id']}/items", json={"article_id": library["anduril"], "verdict": "out"})
    assert said.json() == {"matches": 1}
    assert api.post(f"/api/topics/{created['id']}/items",
                    json={"article_id": library["boats"], "verdict": "in"}).json()["matches"] == 2
    page = api.get(f"/api/topics/{created['id']}").json()
    assert page["by"] == {"words": 0, "meaning": 1, "you": 1}
    items = api.get(f"/api/topics/{created['id']}/articles").json()["items"]
    assert [(item["id"], item["why"]) for item in items] == [(library["boats"], "you"), (library["swarm"], "meaning")]

    took_back = api.post(f"/api/topics/{created['id']}/items", json={"article_id": library["anduril"], "verdict": "none"})
    assert took_back.json()["matches"] == 3
    assert api.post(f"/api/topics/{created['id']}/items", json={"article_id": 99999, "verdict": "in"}).status_code == 404
    assert api.post(f"/api/topics/{created['id']}/items", json={"article_id": 1, "verdict": "maybe"}).status_code == 422


def test_the_preview_counts_what_meaning_adds(api, library):
    body = {"name": "Drone swarms air defence", "terms": ["navy"]}
    assert api.post("/api/topics/preview", json=body).json() == {"matches": 2, "by_meaning": 1, "mentions": 1}
    assert api.post("/api/topics/preview", json={**body, "by_meaning": False}).json() == {
        "matches": 2, "by_meaning": 0, "mentions": 0}
    assert api.post("/api/topics/preview", json={**body, "reach": "wide"}).status_code == 422


# --- the page ------------------------------------------------------------------------------

def test_a_topic_page_says_what_it_is_made_of_and_what_is_next(api, library):
    store("Navy orders unmanned boats", "More unmanned boats for the navy.", source="r/navy", kind="post")
    embed.embed_pending()
    navy = api.post("/api/topics", json={"name": "Navy", "terms": ["navy"], "by_meaning": False}).json()
    drones = api.post("/api/topics", json={"name": "Drone swarms air defence", "terms": ["zebra"]}).json()
    api.post("/api/topics", json={"name": "Wind power", "terms": ["wind"]})

    assert navy["matches"] == 3 and navy["by_meaning"] is False and navy["reach"] == "balanced"
    assert [(s["name"], s["matches"]) for s in navy["sources"]] == [("Example Institute", 2), ("r/navy", 1)]
    assert navy["kinds"] == [{"content_type": "article", "n": 2}, {"content_type": "post", "n": 1}]
    assert navy["news"] is None and navy["earlier"] == [] and navy["meaning"] == {"ready": True, "reason": ""}

    page = api.get(f"/api/topics/{drones['id']}").json()
    assert [entry["name"] for entry in page["up_next"]] == ["Navy", "Wind power"]  # the closest in meaning first
    assert page["up_next"][0]["closeness"] > page["up_next"][1]["closeness"]
    assert (page["previous"]["name"], page["next"]["name"]) == ("Wind power", "Navy")  # the sidebar's order, as a ring

    api.delete(f"/api/topics/{navy['id']}")
    assert [entry["name"] for entry in api.get(f"/api/topics/{drones['id']}").json()["up_next"]] == ["Wind power"]


def test_new_means_newer_than_your_last_visit(api, library):
    created = api.post("/api/topics", json={"name": "Navy", "terms": ["navy"], "by_meaning": False}).json()
    assert created["new"] == 0 and created["visited_at"]  # what was there when the topic was made is not news
    db.execute("UPDATE topics SET visited_at = ? WHERE id = ?", (days_ago(1), created["id"]))
    store("Navy sails north", "The navy sends ships north.")
    assert api.get("/api/topics").json()[0]["new"] == 3  # the fixture's two items and this one were stored after it

    page = api.get(f"/api/topics/{created['id']}").json()
    timeline = api.get(f"/api/topics/{created['id']}/timeline", params={"since": page["visited_at"]}).json()
    assert [entry["new"] for entry in timeline["items"]] == [True, True, True]
    assert api.post(f"/api/topics/{created['id']}/visit").json() == {"visited": True}
    assert api.get(f"/api/topics/{created['id']}").json()["new"] == 0


def test_the_timeline_is_newest_first_and_folds_what_says_the_same_thing():
    first = store("Tanker attacked in the Strait of Hormuz", "A tanker was attacked in the Strait of Hormuz on Monday.",
                  published="2026-10-06T00:00:00Z", source="Reuters")
    again = store("Tanker attacked in the Strait of Hormuz, officials say",
                  "Officials say a tanker was attacked in the Strait of Hormuz on Monday.",
                  published="2026-10-07T00:00:00Z", source="r/energy")
    later = store("Tanker attacked in the Strait of Hormuz", "A tanker was attacked in the Strait of Hormuz on Monday.",
                  published="2026-11-20T00:00:00Z", source="r/energy")  # the same words, six weeks on: another event
    paper = store("Oil exports recover", "Crude oil exports through Hormuz are back at earlier levels.",
                  published="2026-09-30T00:00:00Z", source="Reuters")
    embed.embed_pending()
    found = topic_search.members(topic(name="Hormuz", terms=["hormuz"], by_meaning=False))

    timeline = topic_search.timeline(found)
    assert timeline["total"] == 3
    assert [entry["ids"] for entry in timeline["items"]] == [[later], [again, first], [paper]]
    story = timeline["items"][1]
    assert (story["date"][:10], story["first_date"][:10], story["sources"]) == ("2026-10-07", "2026-10-06", 2)
    assert len(story["more"]) == 1 and story["more"][0]["id"] in (first, again) and story["more"][0]["id"] != story["id"]
    assert topic_search.timeline(found, limit=1, offset=2)["items"][0]["id"] == paper
    assert story["image_url"] == "" and timeline["items"][0]["image_url"] == ""
    db.execute("UPDATE articles SET image_url = 'https://example.org/tanker.jpg' WHERE id = ?", (first,))
    story = topic_search.timeline(found)["items"][1]  # the picture of another item of the same story will do
    assert story["image_url"] == "https://example.org/tanker.jpg"

    config.update({"meaning_enabled": False})  # without embeddings every item is its own entry
    assert topic_search.timeline(found)["total"] == 4


def test_a_trend_compares_shares_and_says_when_there_is_too_little_to_compare():
    today = date(2026, 10, 12)
    stamp = lambda days: (today - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    for days in (1, 2, 3, 4):  # four items on the topic this week ...
        store(f"Hormuz tanker report {days}", "Hormuz.", published=stamp(days))
    for days in (10, 20):  # ... two in the four weeks before
        store(f"Hormuz tanker report {days}", "Hormuz.", published=stamp(days))
    found = topic_search.members(topic(name="Hormuz", terms=["hormuz"], by_meaning=False))

    thin = topic_search.trend(found, today)
    assert thin["short"] == {"now": 4, "before": 2, "label": "too little history", "ratio": None}
    assert (thin["first"], thin["last"]) == ("2026-09-22", "2026-10-11")
    assert len(thin["weeks"]) == 26 and thin["weeks"][-1] == {"start": "2026-10-12", "count": 0, "total": 0}
    assert sum(week["count"] for week in thin["weeks"]) == 6

    for days in range(35):  # the library collects other things all along, five a day
        for n in range(5):
            store(f"Other news {days} {n}", "Something else.", published=stamp(days))
    trend = topic_search.trend(found, today)
    # 4 of 39 this week against 2 of 142 before: the topic's share is more than seven times as large
    assert trend["short"]["label"] == "spiking" and trend["short"]["ratio"] == pytest.approx(7.28, abs=0.01)
    assert trend["long"]["label"] == "too little history"  # nothing in the library is older than five weeks


def test_an_older_library_gets_what_topics_need(api):
    created = api.post("/api/topics", json={"name": "Navy"}).json()
    for column in ("by_meaning", "reach", "auto_update", "visited_at"):
        db.execute(f"ALTER TABLE topics DROP COLUMN {column}")
    db.execute("DROP TABLE topic_notes")
    db.init()
    page = api.get(f"/api/topics/{created['id']}").json()
    assert (page["by_meaning"], page["reach"], page["auto_update"], page["visited_at"]) == (True, "balanced", False, "")
    assert page["new"] == 0  # never visited: nothing is called new


# --- what Claude writes --------------------------------------------------------------------

@pytest.fixture
def hormuz(api) -> dict:
    """A topic with two items from this week and one that is too old to be news."""
    first = store("Tanker attacked in the Strait of Hormuz", "A tanker was attacked in the Strait of Hormuz on Monday, "
                  "the second attack this month, according to shipping companies.", published=days_ago(3))
    second = store("Oil exports through Hormuz recover", "Crude oil exports through the Strait of Hormuz are back at "
                   "the level of before the war, tanker trackers report.", published=days_ago(2))
    old = store("The conflict over Hormuz", "A study of the conflict over the Strait of Hormuz and its history.",
                published=days_ago(60))
    created = api.post("/api/topics", json={"name": "Strait of Hormuz", "terms": ["hormuz"],
                                            "description": "Shipping through the strait."}).json()
    return {**created, "items": {"first": first, "second": second, "old": old}}


def test_the_page_says_what_an_update_would_read_and_cost_before_it_is_written(api, hormuz):
    assert hormuz["news_next"]["waiting"] == 2 and hormuz["news_next"]["reading"] == 2  # the study is not news
    assert hormuz["news_next"]["model_label"] == "Claude Haiku 5.5" and 0 < hormuz["news_next"]["usd"] < 0.001
    assert hormuz["long_run_next"]["reading"] == 3 and hormuz["long_run_next"]["model_label"] == "Claude Opus 5.5"
    assert 0.04 < hormuz["long_run_next"]["usd"] < 0.08  # mostly the answer: 2,500 tokens at $20 a million

    config.update({"model_topic_news": "claude-sonnet-5-5"})
    assert api.get(f"/api/topics/{hormuz['id']}").json()["news_next"]["usd"] == pytest.approx(
        20 * hormuz["news_next"]["usd"], abs=20 * 0.00005)  # the Haiku price is rounded to four decimals
    assert api.post(f"/api/topics/{hormuz['id']}/news").status_code == 400  # no API key


def test_what_is_new_is_written_from_what_arrived_since_the_last_update(api, hormuz, monkeypatch):
    sent = claude_says(monkeypatch, "Exports recovered [1]. A tanker was attacked [2].")
    job = wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    assert job["status"] == "done" and job["result"]["articles_read"] == 2 and job["usage"]["calls"] == 1

    request = sent[0]
    prompt = request["messages"][0]["content"]
    assert request["model"] == "claude-haiku-5-5" and "since the last update" in request["system"]
    assert prompt.index("[1] Oil exports through Hormuz recover") < prompt.index("[2] Tanker attacked")  # newest first
    assert "tanker trackers report" in prompt and "The conflict over Hormuz" not in prompt
    assert "Topic: Strait of Hormuz" in prompt and "Shipping through the strait." in prompt

    page = api.get(f"/api/topics/{hormuz['id']}").json()
    assert page["news"]["text"].startswith("Exports recovered [1]") and page["news"]["items"] == 2
    assert [source["article_id"] for source in page["news"]["sources"]] == [hormuz["items"]["second"],
                                                                          hormuz["items"]["first"]]
    assert page["news_next"] == {"waiting": 0, "reading": 0, "usd": 0, "model_label": "Claude Haiku 5.5"}
    nothing = wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    assert nothing["status"] == "error" and "Nothing new" in nothing["error"] and len(sent) == 1

    time.sleep(1.1)  # "arrived later" is told from the time an item was stored, to the second
    third = store("Iran rejects talks on Hormuz", "Iran rejected new talks about shipping in the Strait of Hormuz, "
                  "state media said on Friday.", published=days_ago(0.1))
    assert api.get(f"/api/topics/{hormuz['id']}").json()["news_next"]["waiting"] == 1
    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    prompt = sent[1]["messages"][0]["content"]
    assert "[1] Iran rejects talks on Hormuz" in prompt and "[2]" not in prompt.split("New items:")[1]
    assert "The previous update" in prompt and "Exports recovered [1]" in prompt  # so that it is not repeated
    page = api.get(f"/api/topics/{hormuz['id']}").json()
    assert page["news"]["sources"][0]["article_id"] == third and len(page["earlier"]) == 1


def test_the_long_run_reads_the_best_items_oldest_first_and_the_updates_before_it(api, hormuz, monkeypatch):
    claude_says(monkeypatch, "Exports recovered [1].")
    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    sent = claude_says(monkeypatch, "## Bottom line\nThe strait stayed open [3].")
    job = wait_for(api, api.post(f"/api/topics/{hormuz['id']}/briefing").json()["job_id"])
    assert job["status"] == "done" and job["title"] == "The long run: Strait of Hormuz"

    request = sent[0]
    prompt = request["messages"][0]["content"]
    assert request["model"] == "claude-opus-5-5" and request["stream"] is True
    assert prompt.index("[1] The conflict over Hormuz") < prompt.index("[3] Oil exports through Hormuz recover")
    assert "Updates written as items arrived" in prompt and "Exports recovered [1]." in prompt
    page = api.get(f"/api/topics/{hormuz['id']}").json()
    assert page["briefing"].startswith("## Bottom line")
    assert [source["article_id"] for source in page["briefing_sources"]] == [hormuz["items"]["second"]]

    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/briefing").json()["job_id"])
    assert "The previous version of this summary" in sent[1]["messages"][0]["content"]


def test_a_text_is_cut_into_headline_opening_line_pictures_and_body():
    sources = [{"n": 1, "image_url": ""}, {"n": 2, "image_url": "https://example.org/2.jpg"},
               {"n": 3, "image_url": "https://example.org/3.jpg"}]
    news = ("# Exports recover as attacks go on\n\nShipping moves again despite a new attack [1].\n\n"
            "[[picture 2]]\n\n- Exports recovered [1].\n- A tanker was attacked [2].")
    assert briefing.article(news, sources) == {
        "headline": "Exports recover as attacks go on", "standfirst": "Shipping moves again despite a new attack [1].",
        "lead": 2, "body": "- Exports recovered [1].\n- A tanker was attacked [2]."}

    long_run = ("# The strait stays open\n\n[[picture 3]]\n\nTraffic is back [3].\n\n## How it developed\n"
                "Attacks came first [1].\n\n[[picture 2]]\n\n## What to watch\nTalks [2].\n[[picture 3]]\n"
                "[[picture 1]]\n[[picture 9]]")
    cut = briefing.article(long_run, sources)
    assert (cut["headline"], cut["standfirst"], cut["lead"]) == ("The strait stays open", "Traffic is back [3].", 3)
    # one more picture between sections; the lead's again, one of an item without a picture, an unknown one: gone
    assert cut["body"] == "## How it developed\nAttacks came first [1].\n\n[[picture 2]]\n\n## What to watch\nTalks [2]."

    picked_none = briefing.article("# Talks stall\n\nNothing moved [1].\n\n- Talks stalled [3], then [2].", sources)
    assert picked_none["lead"] == 3 and picked_none["standfirst"] == "Nothing moved [1]."  # the first cited picture
    # Claude Haiku wrote one long paragraph and put the picture line after it (30 October 2026)
    one_block = briefing.article("# No news on the strait\n\n" + "Nothing moved there this week [1]. " * 20
                                 + "\n\n[[picture 2]]", sources)
    assert one_block["lead"] == 2 and one_block["standfirst"] == "" and one_block["body"].startswith("Nothing moved")
    opening = briefing.article("# Talks stall\n\nTalks stalled [3].\n\nMore on it [2].", sources)
    assert opening["lead"] == 3  # what the opening line cites comes first
    late = briefing.article("# Talks stall\n\nNothing moved [1].\n\nMore text [1].\n\n[[picture 3]]", sources)
    assert (late["lead"], late["body"]) == (3, "More text [1].")  # a picture line at the end still leads
    older = briefing.article("- Exports recovered [1].\n- A tanker was attacked [2].", sources)
    assert older == {"headline": "", "standfirst": "", "lead": 2,  # from before headlines: the first picture cited
                     "body": "- Exports recovered [1].\n- A tanker was attacked [2]."}
    assert briefing.article("", sources) == {"headline": "", "standfirst": "", "lead": 2, "body": ""}


def test_claude_is_told_which_items_have_a_picture_and_the_page_gets_the_article(api, hormuz, monkeypatch):
    db.execute("UPDATE articles SET image_url = 'https://example.org/tanker.jpg' WHERE id = ?",
               (hormuz["items"]["first"],))
    sent = claude_says(monkeypatch, "# Exports recover, a tanker is hit\n\nShipping is back to normal, mostly.\n\n"
                                    "[[picture 2]]\n\nExports recovered [1].")
    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    prompt = sent[0]["messages"][0]["content"]
    assert "[2] Tanker attacked in the Strait of Hormuz\nSource: Example Institute" in prompt
    assert prompt.split("[2] ")[1].split("\n")[1].endswith(" · picture")  # the tanker item has one
    assert not prompt.split("[1] ")[1].split("\n")[1].endswith(" · picture")
    assert "[[picture N]]" in sent[0]["system"] and "headline" in sent[0]["system"]

    card = next(topic for topic in api.get("/api/topics").json() if topic["id"] == hormuz["id"])
    assert card["news"] == "Shipping is back to normal, mostly. Exports recovered."  # no headline, no picture line
    news = api.get(f"/api/topics/{hormuz['id']}").json()["news"]
    assert [source["n"] for source in news["sources"]] == [1, 2]  # 2 is only shown, not cited: it is kept
    assert news["sources"][1]["image_url"] == "https://example.org/tanker.jpg" and news["sources"][0]["image_url"] == ""
    assert news["article"] == {"headline": "Exports recover, a tanker is hit",
                               "standfirst": "Shipping is back to normal, mostly.", "lead": 2,
                               "body": "Exports recovered [1]."}

    sent = claude_says(monkeypatch, "# The strait stays open\n\nIt does [1].\n\n## Then\nMore [2].")
    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/briefing").json()["job_id"])
    prompt = sent[0]["messages"][0]["content"]
    assert "[[picture" not in prompt and "Shipping is back to normal, mostly." in prompt  # the update, as background
    assert "one or two such lines in all" in sent[0]["system"]
    page = api.get(f"/api/topics/{hormuz['id']}").json()
    # Claude named no picture: the first cited item with one, the tanker ([2] here: oldest first)
    assert page["briefing_article"]["headline"] == "The strait stays open" and page["briefing_article"]["lead"] == 2


def test_the_latest_update_can_be_written_again_from_the_same_items(api, hormuz, monkeypatch):
    assert api.get(f"/api/topics/{hormuz['id']}").json()["news_rewrite"] is None  # nothing written yet
    sent = claude_says(monkeypatch, "Exports recovered [1].")  # an update from before headlines
    refused = wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news", params={"rewrite": 1}).json()["job_id"])
    assert refused["status"] == "error" and "no update to write again" in refused["error"] and not sent

    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    time.sleep(1.1)
    store("Iran rejects talks on Hormuz", "Iran rejected new talks about shipping in the Strait of Hormuz.",
          published=days_ago(0.1))
    wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news").json()["job_id"])
    page = api.get(f"/api/topics/{hormuz['id']}").json()
    assert page["news_next"]["waiting"] == 0 and page["news_rewrite"]["reading"] == 1
    assert page["news_rewrite"]["usd"] > 0 and len(page["earlier"]) == 1

    sent = claude_says(monkeypatch, "# Iran rejects talks on the strait\n\nTehran said no [1].\n\nIt said so [1].")
    job = wait_for(api, api.post(f"/api/topics/{hormuz['id']}/news", params={"rewrite": 1}).json()["job_id"])
    assert job["status"] == "done" and "writing the latest update again from 1 item" in job["logs"][0]["msg"]
    prompt = sent[0]["messages"][0]["content"]
    assert "[1] Iran rejects talks on Hormuz" in prompt and "[2]" not in prompt.split("New items:")[1]
    assert "The previous update" in prompt and "Exports recovered [1]" in prompt  # the one before it
    page = api.get(f"/api/topics/{hormuz['id']}").json()
    assert page["news"]["article"]["headline"] == "Iran rejects talks on the strait"
    assert len(page["earlier"]) == 1 and page["earlier"][0]["text"] == "Exports recovered [1]."  # in its place
    assert page["news_next"]["waiting"] == 0 and page["news_rewrite"]["reading"] == 1


def test_a_topic_that_updates_itself_does_so_after_a_scrape_within_what_a_run_may_cost(site, job, monkeypatch):
    sent = claude_says(monkeypatch, "New institute items [1].")
    monkeypatch.setattr(briefing, "NEWS_DAYS", 100_000)  # the fake site's dates are fixed; today's is not
    for name, terms, auto in (("Institute", '["institute", "drone", "climate"]', 1), ("Arctic", '["arctic"]', 1),
                              ("Cyber", '["cyber", "drone", "climate"]', 0)):
        db.execute("INSERT INTO topics(name, terms, auto_update, by_meaning, created_at) VALUES(?,?,?,0,?)",
                   (name, terms, auto, db.now()))

    config.update({"claude_budget_usd": 0.0000001})
    source_id = add_source(institute(site))
    totals = scrape_source(source_id, job)
    assert totals["topics"] == {"updated": 0, "left": 1} and not sent
    assert "left for a later run" in job.text()

    config.update({"claude_budget_usd": 0.5})
    db.execute("DELETE FROM articles")
    totals = scrape_source(source_id, job)
    # Institute has enough new items; Arctic has one, which waits; Cyber does not update itself.
    assert totals["topics"] == {"updated": 1, "left": 0} and len(sent) == 1
    assert "Topic: Institute" in sent[0]["messages"][0]["content"]
    assert db.scalar("SELECT COUNT(*) FROM topic_notes") == 1 and job.usage["calls"] == 1


def test_the_dashboard_can_start_the_embedding_itself(api):
    store("Drone swarms over the Baltic", "Small states buy drone swarms.")
    meta = api.get("/api/meta").json()["meaning"]
    assert (meta["available"], meta["embedded"], meta["pending"]) == (True, 0, 1)
    job = wait_for(api, api.post("/api/meaning/embed").json()["job_id"])
    assert job["status"] == "done" and job["kind"] == "embed" and job["result"] == {"embedded": 1}
    assert api.get("/api/meta").json()["meaning"]["pending"] == 0
    assert api.post("/api/meaning/embed").status_code == 400  # nothing left to do


def test_a_larger_library_has_its_average_taken_off_every_embedding(monkeypatch):
    monkeypatch.setattr(embed, "CENTRE_FROM", 4)
    for n in range(3):
        store(f"Energy policy report number {n}", "Energy policy in Europe.")
    embed.embed_pending()
    small = embed.index()
    assert small.centre is None and small.bar(0.4) == pytest.approx(0.5)  # too few items: stricter instead
    assert float(small.matrix[0] @ small.matrix[1]) > 0.8  # what the items share makes them all look alike

    drones = store("Drone swarms over the Baltic", "Small states buy drone swarms.")
    embed.embed_pending()
    index = embed.index()
    assert index.centre is not None and index.bar(0.4) == 0.4
    lengths = (index.matrix ** 2).sum(axis=1) ** 0.5
    assert lengths == pytest.approx([1, 1, 1, 1], abs=1e-5)
    question = index.place(embed.encode_query("drone swarms"))
    assert meaning.nearest(question, 1)[0][0] == drones
    assert float(index.matrix[0] @ index.matrix[index.row[drones]]) < 0  # the odd one out is far from the rest


def test_starting_the_platform_embeds_what_was_stored_without_embeddings():
    store("Drone swarms over the Baltic", "Small states buy drone swarms.")
    with TestClient(app) as started:
        jobs = [job for job in started.get("/api/jobs").json() if job["kind"] == "embed"]
        assert len(jobs) == 1 and wait_for(started, jobs[0]["id"])["status"] == "done"
        assert started.get("/api/meta").json()["meaning"]["pending"] == 0
    config.update({"meaning_enabled": False})
    store("Wind turbines in the North Sea", "A new wind farm opens.")
    with TestClient(app) as started:  # switched off: nothing is started, and nothing is embedded
        assert [job for job in started.get("/api/jobs").json() if job["status"] in ("queued", "running")] == []
    assert db.scalar("SELECT COUNT(*) FROM embeddings") == 1


# --- a topic as a card on Home ---------------------------------------------------------------------

def test_a_topic_card_shows_pictures_of_its_newest_items_or_the_one_you_pinned(api):
    def pictured(title: str, days: float, source: str, picture: str) -> int:
        article_id = store(title, "A tanker story.", published=days_ago(days), source=source)
        db.execute("UPDATE articles SET image_url = ? WHERE id = ?", (picture, article_id))
        return article_id

    pictured("Tanker attacked off the coast", 1, "Wire", "https://img.example/a1.jpg")
    pictured("Second tanker attacked", 2, "Wire", "https://img.example/a2.jpg")
    pictured("Tanker insurance rises", 3, "Journal", "https://img.example/b1.jpg")
    pictured("Tanker report without a picture", 0.5, "Journal", "")
    pictured("Tanker story with the same wire photo", 4, "Blog", "https://img.example/a1.jpg")
    created = api.post("/api/topics", json={"name": "Tankers", "terms": ["tanker"], "by_meaning": False}).json()
    api.post("/api/topics", json={"name": "Nothing yet", "terms": ["zeppelin"], "by_meaning": False})

    empty, card = api.get("/api/topics").json()
    assert (empty["name"], empty["cover"], empty["latest"], empty["news"]) == ("Nothing yet", [], "", "")
    # newest first, and a source gets one picture before any source gets a second; the repeated photo once
    assert card["cover"] == ["https://img.example/a1.jpg", "https://img.example/b1.jpg", "https://img.example/a2.jpg"]
    assert card["pinned"] is False and card["matches"] == 5 and card["latest"][:10] == days_ago(0.5)[:10]
    assert card["trend"] in ("spiking", "steady", "quieter", "quiet", "too little history") and card["news"] == ""

    db.execute("INSERT INTO topic_notes(topic_id, text, created_at) VALUES(?, ?, ?)", (created["id"], (
        "## The last days\n\nTwo tankers were **attacked** within a day [1, 2], and insurers reacted [3].\n\n"
        "- Rates for the route doubled [3].\n" + "- More of the same. " * 30), db.now()))
    news = api.get("/api/topics").json()[1]["news"]
    assert news.startswith("Two tankers were attacked within a day, and insurers reacted. Rates for the route doubled.")
    assert len(news) <= 221 and news.endswith("…") and "[" not in news and "#" not in news

    page = api.get(f"/api/topics/{created['id']}").json()
    assert page["pictures"] == card["cover"] and page["cover_url"] == ""  # what the editor offers to choose from
    pinned = api.patch(f"/api/topics/{created['id']}", json={"cover_url": "https://img.example/b1.jpg"}).json()
    assert pinned["cover_url"] == "https://img.example/b1.jpg" and pinned["name"] == "Tankers"
    card = api.get("/api/topics").json()[1]
    assert card["cover"] == ["https://img.example/b1.jpg"] and card["pinned"] is True
    assert api.patch(f"/api/topics/{created['id']}", json={"name": "Tankers at sea"}).json()["cover_url"].endswith("b1.jpg")
    assert api.patch(f"/api/topics/{created['id']}", json={"cover_url": "javascript:alert(1)"}).status_code == 422
    api.patch(f"/api/topics/{created['id']}", json={"cover_url": ""})  # back to automatic
    assert api.get("/api/topics").json()[1]["pinned"] is False and len(api.get("/api/topics").json()[1]["cover"]) == 3


# --- the languages term suggestions are asked for ---------------------------------------------------

ENGLISH_TEXT = ("The ministry said the new programme for coastal defence would start next year, and that the navy "
                "would take part in it with two of its ships and a number of its people.")
DUTCH_TEXT = ("De marine krijgt volgend jaar twee nieuwe schepen voor de bescherming van de kust, zegt het "
              "ministerie van Defensie in een verklaring die het op dinsdag heeft uitgebracht.")


def test_term_suggestions_go_by_the_languages_items_are_written_in(monkeypatch):
    from backend.ai import client as ai
    from backend.search import expand

    def labelled(title: str, text: str, language: str) -> None:
        db.execute("UPDATE articles SET language = ? WHERE id = ?", (language, store(title, text)))

    for number in range(30):
        labelled(f"English item {number}", ENGLISH_TEXT, "en")
    for number in range(12):  # English bulletins whose site labels its pages Polish, as PISM's does
        labelled(f"PISM bulletin {number}", ENGLISH_TEXT, "pl")
    labelled("Der Krieg im Sudan", "Der Krieg im Sudan dauert seit April 2023 an, und die Lage der Menschen in "
             "dem Land wird nach Angaben der Helfer von Woche zu Woche immer schlechter.", "de")
    assert expand.library_languages() == ["en"]  # the bulletins are English; one German item is no language of it

    sent: list[dict] = []
    monkeypatch.setattr(ai, "structured", lambda **request: sent.append(request) or
                        {"description": "", "required_any": [], "terms": ["navy"]})
    expand.expand_topic("Navy")
    assert sent[0]["prompt"] == "Topic: Navy\nLanguages of the library: only English: give no translations"
    assert "a term in any other language would match nothing" in sent[0]["system"]

    for number in range(12):  # a source in Dutch, not translated: now Dutch terms find something
        labelled(f"Nederlands bericht {number}", DUTCH_TEXT, "nl")
    assert expand.library_languages() == ["en", "nl"]
    expand.expand_topic("Navy")
    assert sent[1]["prompt"].endswith("Languages of the library: nl (besides English)")
    db.execute("UPDATE articles SET translated_from = 'nl' WHERE language = 'nl'")  # once translated, it is English
    assert expand.library_languages() == ["en"]
