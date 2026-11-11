"""Home's front page (backend/api/home.py): the newest topic update per topic as its headlines, and what reached
the library since the last visit."""

from __future__ import annotations

import json

from backend import db
from backend.api import home
from tests.test_meaning import api, days_ago, store  # noqa: F401  (api is a fixture)


def note(topic_id: int, text: str, written: str, sources: list[dict] | None = None) -> None:
    db.execute("INSERT INTO topic_notes(topic_id, text, sources, items, created_at) VALUES(?, ?, ?, ?, ?)",
               (topic_id, text, json.dumps(sources or []), len(sources or []), written))


def test_the_newest_update_of_each_topic_leads_with_its_picture(api):  # noqa: F811
    tanker = store("Tanker attacked off the coast", "A tanker story.", source="Wire")
    db.execute("UPDATE articles SET image_url = 'https://img.example/t.jpg' WHERE id = ?", (tanker,))
    tankers = api.post("/api/topics", json={"name": "Tankers", "terms": ["tanker"], "by_meaning": False}).json()
    chips = api.post("/api/topics", json={"name": "Chips", "terms": ["chip"], "by_meaning": False}).json()
    api.post("/api/topics", json={"name": "Quiet", "terms": ["zeppelin"], "by_meaning": False})
    source = {"n": 1, "article_id": tanker, "title": "Tanker attacked off the coast", "url": "u",
              "source_name": "Wire", "date": "2026-11-10"}
    note(tankers["id"], "# An older headline\n\nOld opening.\n\nOld body [1].", days_ago(3), [source])
    note(chips["id"], "Export controls tighten again, and fabs move [1].", days_ago(1), [source])
    note(tankers["id"], "# Tankers come under fire again\n\nTwo attacks in a day.\n\n[[picture 1]]\n\nMore [1].",
         days_ago(0.1), [source])

    stories = api.get("/api/home").json()["stories"]
    assert [story["topic_name"] for story in stories] == ["Tankers", "Chips"]  # one per topic, newest first
    lead = stories[0]
    assert lead["headline"] == "Tankers come under fire again" and lead["standfirst"] == "Two attacks in a day."
    assert lead["image_url"] == "https://img.example/t.jpg" and lead["items"] == 1 and lead["sources"] == 1
    # a text from before headlines: named after its topic, opened with its first words, without numbers
    assert stories[1]["headline"] == "What is new: Chips"
    assert stories[1]["standfirst"] == "Export controls tighten again, and fabs move."


def test_since_the_last_visit_counts_items_sources_and_topics(api):  # noqa: F811
    api.post("/api/topics", json={"name": "Tankers", "terms": ["tanker"], "by_meaning": False})
    store("Tanker attacked off the coast", "A tanker story.", source="Wire")
    db.execute("UPDATE articles SET fetched_at = ?", (days_ago(5),))  # long before
    first = api.post("/api/home/visit").json()["since"]
    assert first[:10] == days_ago(1)[:10]  # never here before: the last day counts
    assert api.get("/api/home").json()["since"]["items"] == 0

    db.execute("UPDATE settings SET value = ? WHERE key = ?", (json.dumps(days_ago(2)), home.SEEN))  # you left
    store("Second tanker attacked", "Another tanker story.", source="Journal")
    store("Wind farm opens", "Turbines.", source="Journal")
    api.post("/api/home/visit")
    since = api.get("/api/home").json()["since"]
    assert since["at"][:10] == days_ago(2)[:10] and since["items"] == 2
    assert since["sources"] == [{"name": "Journal", "new": 2}]
    assert [(topic["name"], topic["new"]) for topic in since["topics"]] == [("Tankers", 1)]

    api.post("/api/home/visit")  # back on Home ten minutes later: the same visit, the same counts
    assert api.get("/api/home").json()["since"]["items"] == 2
