"""The ask add-on (backend/addons/ask): items split into passages, the passages found for a question, and Claude's
answer with its citations.

Claude is a stand-in that answers what each test tells it to, citations included; the embeddings come from the
word-counting stand-in, so "close in meaning" here means "shares words".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend import db, removed
from backend.addons.ask import answer, find, passages, store
from backend.ai import client as ai
from backend.pipeline.scrape import store_article
from tests.test_meaning import api, by_meaning, wait_for  # noqa: F401 - fixtures
from tests.test_pipeline import add_source
from backend.schemas import Recipe

SENTENCE = "The navy tests unmanned boats in the harbour of Den Helder to learn how they behave in rough weather. "
DRONES = ("Drone swarms change air defence for small states. Cheap interceptors are bought in large numbers, and "
          "the air force trains crews to fight swarms at night. ")
WIND = "A new wind farm opens off the coast of Zeeland, and the grid operator builds a new cable to carry its power. "


@pytest.fixture(autouse=True)
def empty_tables():
    store.init()
    for table in ("ask_passages", "ask_done", "ask_questions"):
        db.execute(f"DELETE FROM {table}")
    passages.forget()


def item(title: str, text: str, *, summary: str = "", source: str = "Example Institute",
         published: str = "2026-10-01T00:00:00Z") -> int:
    found = db.row("SELECT id FROM sources WHERE name = ?", (source,))
    source_id = found["id"] if found else add_source(Recipe(site_name=source, homepage="https://example.org"))
    return store_article(source_id, "Feed", {
        "url": f"https://example.org/{source}/{abs(hash((title, text)))}", "title": title, "author": "",
        "published_at": published, "summary": summary, "text": text, "image_url": "", "pdf_url": "",
        "content_type": "report", "language": "en", "tags": "", "word_count": len(text.split()), "is_partial": False,
    })


@pytest.fixture
def library() -> dict:
    ids = {
        "boats": item("Unmanned boats for the navy", "\n\n".join([SENTENCE * 4, SENTENCE * 3]),
                      summary="The navy tests unmanned boats."),
        "drones": item("Drone swarms and air defence", DRONES * 12, summary="Drone swarms change air defence."),
        "wind": item("Wind turbines in the North Sea", WIND * 3, source="Energy Desk"),
    }
    passages.split_pending()
    return ids


# --- splitting ---------------------------------------------------------------------------------

def test_a_text_is_split_into_passages_at_sentence_ends():
    found = passages.split(DRONES * 12)
    assert len(found) > 1
    assert all(len(passage) <= passages.MAX_CHARS for passage in found)
    assert all(passage.endswith(".") for passage in found)  # whole sentences
    assert " ".join(found) == " ".join((DRONES * 12).split())  # nothing lost


def test_pieces_that_say_nothing_are_left_out():
    text = "\n\n".join(["Page 4", "12.4 18.9 22.1 31.0 44.2 51.7 60.3 72.8 81.4 90.0 91.2 99.9 100.1",
                        "https://example.org/a https://example.org/b https://example.org/c " * 3, SENTENCE])
    assert passages.split(text) == [SENTENCE.strip()]


def test_the_first_passage_is_the_title_and_summary_and_the_text_follows(library):
    rows = db.rows("SELECT position, text FROM ask_passages WHERE article_id = ? ORDER BY position",
                   (library["drones"],))
    assert rows[0]["text"] == "Drone swarms and air defence. Drone swarms change air defence."
    assert len(rows) > 2 and all("swarm" in row["text"].lower() for row in rows)
    assert passages.pending() == 0
    status = passages.status()
    assert status["done"] == status["items"] == 3 and status["passages"] == db.scalar("SELECT COUNT(*) FROM ask_passages")


def test_an_item_whose_words_change_is_split_again(library):
    before = db.scalar("SELECT COUNT(*) FROM ask_passages WHERE article_id = ?", (library["wind"],))
    db.execute("UPDATE articles SET text = ? WHERE id = ?", (WIND * 9, library["wind"]))
    assert passages.pending() == 1
    passages.split_pending()
    assert db.scalar("SELECT COUNT(*) FROM ask_passages WHERE article_id = ?", (library["wind"],)) > before
    assert passages.pending() == 0


def test_the_passages_of_a_removed_item_are_swept_up(library):
    removed.remove([library["boats"]])
    assert db.scalar("SELECT COUNT(*) FROM ask_passages WHERE article_id = ?", (library["boats"],)) > 0
    assert passages.split_pending()["swept"] == 1
    assert db.scalar("SELECT COUNT(*) FROM ask_passages WHERE article_id = ?", (library["boats"],)) == 0
    assert db.scalar("SELECT COUNT(*) FROM ask_vectors v LEFT JOIN ask_passages p ON p.id = v.passage_id"
                     " WHERE p.id IS NULL") == 0  # their embeddings went with them
    assert db.scalar("SELECT COUNT(*) FROM ask_fts WHERE ask_fts MATCH 'harbour'") == 0  # and their words


# --- finding -----------------------------------------------------------------------------------

def test_a_question_finds_the_passages_that_answer_it(library):
    found = find.find("How does the navy test unmanned boats?")
    assert found.items[0]["id"] == library["boats"]
    assert library["wind"] not in [entry["id"] for entry in found.items]


def test_words_find_a_name_and_no_item_gives_more_than_three_passages(library):
    found = find.find("What happens in Den Helder?", limit=50)
    assert found.items[0]["id"] == library["boats"]
    assert all(len(entry["passages"]) <= find.PER_ITEM for entry in found.items)
    positions = [passage["position"] for passage in found.items[0]["passages"]]
    assert positions == sorted(positions)  # in reading order


def test_a_question_can_be_kept_to_one_source(library):
    source_id = db.scalar("SELECT source_id FROM articles WHERE id = ?", (library["wind"],))
    found = find.find("What does the navy do with drones and boats?", source_id=source_id)
    assert [entry["id"] for entry in found.items] in ([], [library["wind"]])


def test_the_keywords_of_a_question():
    assert find.keywords('What did the "European Defence Fund" do with drones in 2025?') == [
        "European Defence Fund", "drones", "2025"]


# --- answering ---------------------------------------------------------------------------------

def claude_cites(monkeypatch, parts) -> list[dict]:
    """Make Claude answer with `parts`: (text, [(search result, first block, end block), ...])."""
    sent: list[dict] = []

    def fake_message(*, model, usage=None, stream=False, **request):
        sent.append({**request, "model": model})
        content = [SimpleNamespace(type="thinking", thinking="")]
        for text, cites in parts:
            citations = [SimpleNamespace(type="search_result_location", search_result_index=r, start_block_index=s,
                                         end_block_index=e, cited_text="") for r, s, e in cites]
            content.append(SimpleNamespace(type="text", text=text, citations=citations or None))
        reply = SimpleNamespace(stop_reason="end_turn", stop_details=None, content=content,
                                usage=SimpleNamespace(input_tokens=5000, output_tokens=800, cache_read_input_tokens=0,
                                                      cache_creation_input_tokens=0))
        if usage is not None:
            usage.add(model, reply.usage)
        return reply

    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "message", fake_message)
    return sent


def test_a_question_is_priced_before_it_is_asked(api, library):
    plan = api.post("/api/ask/plan", json={"question": "How does the navy test unmanned boats?"}).json()
    assert plan["items"] >= 1 and plan["passages"] >= 1 and 0 < plan["usd"] < 0.1
    assert plan["model_label"] == "Claude Sonnet 5.5" and plan["titles"][0]["article_id"] == library["boats"]


def test_a_question_is_answered_with_its_sources_and_the_passages_cited(api, library, monkeypatch):
    sent = claude_cites(monkeypatch, [
        ("The navy tests unmanned boats in Den Helder.", [(0, 1, 2)]),
        ("\n\nNothing in the library says how many it will buy.", []),
    ])
    asked = api.post("/api/ask", json={"question": "How does the navy test unmanned boats?"}).json()
    assert wait_for(api, asked["job_id"])["status"] == "done"
    request = sent[0]
    results = [block for block in request["messages"][0]["content"] if block["type"] == "search_result"]
    assert results and all(block["citations"] == {"enabled": True} for block in results)
    assert request["messages"][0]["content"][-1] == {"type": "text", "text": "How does the navy test unmanned boats?"}
    assert request["thinking"] == {"type": "adaptive"} and request["model"] == "claude-sonnet-5-5"

    page = api.get(f"/api/ask/questions/{asked['id']}").json()
    assert page["status"] == "done"
    assert page["answer"] == ("The navy tests unmanned boats in Den Helder.[1]\n\n"
                              "Nothing in the library says how many it will buy.")
    first = page["sources"][0]
    assert first["n"] == 1 and first["article_id"] == library["boats"] and not first["gone"]
    assert first["quotes"] and "Den Helder" in first["quotes"][0]
    assert all(entry["article_id"] != library["boats"] for entry in page["read"])  # the others it read
    assert page["cost_usd"] > 0
    assert api.get("/api/ask/questions").json()[0] | {"cited": 1} == api.get("/api/ask/questions").json()[0]


def test_when_nothing_matches_claude_is_not_asked(api, library, monkeypatch):
    sent = claude_cites(monkeypatch, [("Should not be asked.", [])])
    topic_id = db.execute("INSERT INTO topics(name, created_at, required_any, terms) VALUES('Empty', ?, '[\"zzzz\"]',"
                          " '[\"zzzz\"]')", (db.now(),)).lastrowid
    asked = api.post("/api/ask", json={"question": "What about the navy?", "topic_id": topic_id}).json()
    assert wait_for(api, asked["job_id"])["status"] == "done"
    page = api.get(f"/api/ask/questions/{asked['id']}").json()
    assert sent == [] and page["answer"].startswith("The library has nothing") and page["scope"]["topic_name"] == "Empty"


def test_a_refusal_is_kept_as_a_failed_question(api, library, monkeypatch):
    claude_cites(monkeypatch, [])
    original = ai.message

    def refusing(**request):
        reply = original(**request)
        reply.stop_reason = "refusal"
        return reply

    monkeypatch.setattr(ai, "message", refusing)
    asked = api.post("/api/ask", json={"question": "How does the navy test unmanned boats?"}).json()
    assert wait_for(api, asked["job_id"])["status"] == "error"
    page = api.get(f"/api/ask/questions/{asked['id']}").json()
    assert page["status"] == "failed" and "declined" in page["error"]
    assert api.delete(f"/api/ask/questions/{asked['id']}").json() == {"removed": True}


def test_asking_needs_a_key(api, library):
    response = api.post("/api/ask", json={"question": "How does the navy test unmanned boats?"})
    assert response.status_code == 400 and "API key" in response.json()["detail"]


def test_the_dashboard_is_told_about_the_add_on(api):
    meta = api.get("/api/meta").json()
    assert meta["addons"]["ask"] == {"questions": 0, "model_label": "Claude Sonnet 5.5"}
    keys = {spec["key"] for spec in api.get("/api/settings").json()["spec"]}
    assert {"model_ask", "ask_passages"} <= keys
    assert answer.model() == "claude-sonnet-5-5"


def test_footnotes_and_reference_lists_are_left_out():
    notes = ("12 Julian Borger, ‘The Drone Operators Who Halted Russian Armoured Vehicles’, The Guardian, 28 March 2025, "
             "<https://www.theguardian.com/world/2025/mar/28/drones>, accessed 3 April 2025. 13 David Hambling, "
             "‘Every Single Drone’, Forbes, 2 May 2025, https://www.forbes.com/sites/drones, accessed 4 May 2025.")
    assert passages.reference_list(notes)
    quoted = ("“If it has to be months from now or longer than that, we will do that,” Carney said in 2026, when he was "
              "asked whether an agreement with the United States was still possible before the end of the year.")
    assert not passages.reference_list(quoted)
    assert passages.split("\n\n".join([SENTENCE * 3, notes])) == [" ".join((SENTENCE * 3).split())]
