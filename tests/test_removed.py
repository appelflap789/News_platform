"""Removing an item from the library yourself: it stays out of every later scrape, and it can be put back."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import config, db, removed
from backend.main import app
from backend.search import embed
from tests.conftest import Handler
from tests.test_api import add_institute, wait_for


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def by_title(api: TestClient, words: str) -> dict:
    found = api.get("/api/articles", params={"q": words, "sort": "relevance"}).json()["items"]
    return api.get(f"/api/articles/{found[0]['id']}").json()


def scrape(api: TestClient, source_id: int, deep: bool = False) -> dict:
    job = wait_for(api, api.post(f"/api/sources/{source_id}/scrape", json={"deep": deep}).json()["job_id"])
    assert job["status"] == "done", job
    return job


def test_a_removed_item_is_gone_from_everything_and_no_scrape_brings_it_back(api, site):
    source_id = add_institute(api, site)
    article = by_title(api, "anduril drone")

    gone = api.delete(f"/api/articles/{article['id']}").json()
    assert gone["deleted"] is True and gone["title"] == article["title"]
    assert api.get(f"/api/articles/{article['id']}").status_code == 404
    assert api.get("/api/articles", params={"q": "anduril drone"}).json()["total"] == 0
    assert api.get("/api/stats").json() | {"content_types": 0} == {
        "sources": 1, "articles": 8, "topics": 0, "removed": 1, "favorites": 0, "content_types": 0}
    assert api.get(f"/api/sources/{source_id}").json()["article_count"] == 8
    assert api.delete(f"/api/articles/{article['id']}").status_code == 404  # it is not there to remove twice

    listed = api.get("/api/removed").json()
    assert listed["total"] == 1
    assert listed["items"][0] | {"removed_at": ""} == {
        "id": gone["removed_id"], "url": article["url"], "title": article["title"], "source_id": source_id,
        "source_name": "Example Institute", "content_type": "report", "published_at": article["published_at"],
        "removed_at": "", "kept": True}

    # an update and a walk through the whole archive both leave it out, and say so
    Handler.hits.clear()
    update = scrape(api, source_id)
    assert update["result"]["new"] == 0
    deep = scrape(api, source_id, deep=True)
    assert deep["result"]["new"] == 0 and deep["result"]["failed"] == 0
    assert "/publications?page=2" in Handler.hits  # the archive was walked to its end ...
    assert not any(hit.startswith("/publications/p3") for hit in Handler.hits)  # ... and its page not even opened
    assert any("1 that you removed and that stay out" in line["msg"] for line in deep["logs"])
    assert api.get("/api/stats").json()["articles"] == 8


def test_a_removed_item_is_put_back_exactly_as_it_was(api, site):
    config.update({"meaning_enabled": True})
    add_institute(api, site)
    article = by_title(api, "anduril drone")
    # what makes an item more than what a scrape would store again: Claude's work, and what you said about it
    db.execute("UPDATE articles SET ai_summary = 'A summary that was paid for.', translated_from = 'de',"
               " original_title = 'Der Titel' WHERE id = ?", (article["id"],))
    embed.embed_pending()
    vector = db.scalar("SELECT vector FROM embeddings WHERE article_id = ?", (article["id"],))
    topic = api.post("/api/topics", json={"name": "Autonomy", "terms": ["drone"]}).json()
    api.post(f"/api/topics/{topic['id']}/items", json={"article_id": article["id"], "verdict": "out"})
    before = api.get(f"/api/articles/{article['id']}").json()

    gone = api.delete(f"/api/articles/{article['id']}").json()
    assert db.scalar("SELECT COUNT(*) FROM embeddings WHERE article_id = ?", (article["id"],)) == 0
    assert len(embed.index()) == 8  # search by meaning no longer knows it either

    back = api.post(f"/api/removed/{gone['removed_id']}/restore").json()
    assert back == {"restored": True, "article_id": article["id"], "title": article["title"]}
    assert api.get(f"/api/articles/{article['id']}").json() == before
    assert db.scalar("SELECT vector FROM embeddings WHERE article_id = ?", (article["id"],)) == vector
    assert embed.pending() == 0 and len(embed.index()) == 9
    assert db.scalar("SELECT verdict FROM topic_items WHERE topic_id = ? AND article_id = ?",
                     (topic["id"], article["id"])) == "out"
    assert api.get("/api/articles", params={"q": "anduril drone"}).json()["total"] == 1  # found by its words again
    assert api.get("/api/removed").json() == {"total": 0, "items": []}
    assert api.post(f"/api/removed/{gone['removed_id']}/restore").status_code == 404


def test_what_you_removed_stays_out_when_its_source_is_added_again(api, site):
    source_id = add_institute(api, site)
    article = by_title(api, "anduril drone")
    gone = api.delete(f"/api/articles/{article['id']}").json()

    api.delete(f"/api/sources/{source_id}")
    assert api.get("/api/removed").json()["items"][0] | {"removed_at": ""} == {
        "id": gone["removed_id"], "url": article["url"], "title": article["title"], "source_id": None,
        "source_name": "Example Institute", "content_type": "report", "published_at": article["published_at"],
        "removed_at": "", "kept": False}
    assert db.scalar("SELECT item FROM removed") == ""  # the copy went with the source

    again = add_institute(api, site)
    assert api.get(f"/api/sources/{again}").json()["article_count"] == 8

    # it cannot be put back as it was, so it is let in again: the next scrape collects it
    back = api.post(f"/api/removed/{gone['removed_id']}/restore").json()
    assert back == {"restored": False, "article_id": None, "title": article["title"]}
    assert scrape(api, again, deep=True)["result"]["new"] == 1
    assert api.get(f"/api/sources/{again}").json()["article_count"] == 9


def test_saving_a_removed_item_by_its_address_puts_it_back(api, site):
    saved = wait_for(api, api.post("/api/links", json={"url": f"{site}/publications/p1"}).json()["job_id"])
    article_id = saved["result"]["article_id"]
    api.delete(f"/api/articles/{article_id}")

    again = api.post("/api/links", json={"url": f"{site}/publications/p1"}).json()
    assert again == {"job_id": None, "article_id": article_id, "already": True, "put_back": True}
    assert api.get("/api/removed").json()["total"] == 0 and api.get(f"/api/articles/{article_id}").status_code == 200


def test_nothing_stores_a_removed_address_and_a_run_survives_an_item_being_removed(site, job):
    from backend.pipeline import scrape as pipeline
    from backend.pipeline.translate import translate_articles

    source_id = db.execute("INSERT INTO sources(name, url, recipe, created_at) VALUES('S', ?, '{}', ?)",
                           (site, db.now())).lastrowid
    article = {"url": f"{site}/x", "title": "A title of some length", "author": "", "published_at": "", "summary": "",
               "text": "Ein Text auf Deutsch, der übersetzt werden müsste.", "image_url": "", "pdf_url": "",
               "content_type": "article", "language": "de", "tags": "", "word_count": 8, "is_partial": False}
    article_id = pipeline.store_article(source_id, "Feed", article)
    assert [entry["article_id"] for entry in removed.remove([article_id, 99999])] == [article_id]
    assert pipeline.store_article(source_id, "Feed", article) is None  # whichever way it comes in
    assert removed.among([f"{site}/x", f"{site}/y"]) == {f"{site}/x"}

    # a run that was going to translate the item finds it gone and carries on
    waiting = pipeline.store_article(source_id, "Feed", {**article, "url": f"{site}/z"})
    rows = [{"id": waiting, "title": "A title of some length", "chars": 50}]
    removed.remove([waiting])
    from backend.pipeline import translate

    original, translate._waiting = translate._waiting, lambda ids: rows
    try:
        result = translate_articles([waiting], job, usage=None)
    finally:
        translate._waiting = original
    assert result["translated"] == 0 and result["failed"] == 0


def test_an_item_put_back_after_its_number_was_given_away_gets_a_new_one(site):
    source_id = db.execute("INSERT INTO sources(name, url, recipe, created_at) VALUES('S', ?, '{}', ?)",
                           (site, db.now())).lastrowid
    first = db.execute("INSERT INTO articles(source_id, url, title, fetched_at) VALUES(?, ?, 'First', ?)",
                       (source_id, f"{site}/first", db.now())).lastrowid
    entry = removed.remove([first])[0]
    db.execute("INSERT INTO articles(id, source_id, url, title, fetched_at) VALUES(?, ?, ?, 'Second', ?)",
               (first, source_id, f"{site}/second", db.now()))
    back = removed.restore(entry["id"])
    assert back["restored"] and back["article_id"] != first
    assert db.scalar("SELECT title FROM articles WHERE id = ?", (back["article_id"],)) == "First"


def test_favorites_are_starred_listed_counted_and_kept_through_a_removal(api, site):
    add_institute(api, site)
    first, second = (by_title(api, words) for words in ("anduril drone", "arctic security"))
    assert api.get("/api/stats").json()["favorites"] == 0 and first["favorite_at"] == ""

    starred = api.put(f"/api/articles/{second['id']}/favorite", json={"on": True}).json()
    assert starred["favorite_at"]
    db.execute("UPDATE articles SET favorite_at = '2026-10-01T09:00:00Z' WHERE id = ?", (second["id"],))
    api.put(f"/api/articles/{first['id']}/favorite", json={})  # starring is the default
    shelf = api.get("/api/articles", params={"favorites": True}).json()
    assert shelf["total"] == 2 and [item["id"] for item in shelf["items"]] == [first["id"], second["id"]]  # last starred first
    assert shelf["items"][0]["favorite_at"] and api.get("/api/stats").json()["favorites"] == 2
    words = api.get("/api/articles", params={"favorites": True, "q": "arctic"}).json()
    assert [item["id"] for item in words["items"]] == [second["id"]]  # searching within the favorites

    gone = api.delete(f"/api/articles/{first['id']}").json()  # removed and put back: still a favorite
    api.post(f"/api/removed/{gone['removed_id']}/restore")
    assert api.get(f"/api/articles/{first['id']}").json()["favorite_at"]

    assert api.put(f"/api/articles/{first['id']}/favorite", json={"on": False}).json() == {"favorite_at": ""}
    assert api.get("/api/stats").json()["favorites"] == 1
    assert api.put("/api/articles/99999/favorite", json={"on": True}).status_code == 404
