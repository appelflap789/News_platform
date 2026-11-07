"""The foresight add-on (backend/addons/foresight): reading a signal against the library, the rings of
consequences, the signposts watched after a scrape, the re-check, and that the platform works without it.

Claude is a stand-in that answers what each test tells it to; the embeddings come from the word-counting
stand-in, so "close in meaning" here means "shares words".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend import addons, db
from backend.addons.foresight import library, store, watch
from backend.ai import client as ai
from backend.search import embed
from tests.test_meaning import api, by_meaning, days_ago, store as save, wait_for  # noqa: F401 - fixtures

READ = "read this foresight"
EXPAND = "work out what follows from this consequence"
LINKS = "find links between these consequences"
RECHECK = "re-check this foresight"


@pytest.fixture(autouse=True)
def no_foresights():
    store.init()
    db.execute("DELETE FROM foresights")


def claude_answers(monkeypatch, answers: dict) -> list[dict]:
    """Make Claude answer `answers[task]` (a dict, or a function of the request); returns the requests sent."""
    sent: list[dict] = []

    def fake_structured(*, model, system, prompt, schema, task, effort="low", max_tokens=4000, usage=None,
                        stream=False):
        request = {"model": model, "system": system, "prompt": prompt, "task": task, "schema": schema,
                   "stream": stream}
        sent.append(request)
        if usage is not None:
            usage.add(model, SimpleNamespace(input_tokens=3000, output_tokens=900, cache_read_input_tokens=0,
                                             cache_creation_input_tokens=0))
        answer = answers[task]
        return answer(request) if callable(answer) else answer

    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "structured", fake_structured)
    return sent


def consequence(text: str, *, sources=(), basis="library", signposts=(), dampening=False, **fields) -> dict:
    return {"text": text, "mechanism": fields.get("mechanism", "Because it follows."), "domain": "energy",
            "horizon": "months", "likelihood": fields.get("likelihood", "likely"), "basis": basis,
            "sources": list(sources), "dampening": dampening, "signposts": list(signposts)}


@pytest.fixture
def hormuz() -> dict:
    """Three items about the strait (oldest first: Qatar, crude, products) and one about something else."""
    ids = {
        "qatar": save("Qatar LNG trains damaged near the Strait of Hormuz",
                      "Qatar lost LNG capacity at Ras Laffan near the Strait of Hormuz; repairs take years.",
                      published=days_ago(10)),
        "crude": save("Crude exports through the Strait of Hormuz recover",
                      "Crude oil exports through the Strait of Hormuz are back near pre-war levels under escort.",
                      published=days_ago(5)),
        "products": save("Refined products still held up in the Strait of Hormuz",
                         "Diesel and jet fuel shipments through the Strait of Hormuz remain half of normal.",
                         published=days_ago(3)),
        "wind": save("Wind turbines in the North Sea", "A new wind farm opens off the Dutch coast.",
                     published=days_ago(2)),
    }
    embed.embed_pending()
    return ids


DIESEL_SIGNPOST = {"text": "Diesel shortage in Europe deepens as refined products stay blocked",
                   "direction": "for", "terms": ["diesel shortage"]}


def first_reading() -> dict:
    return {
        "standing": "partly", "restated": "Hormuz is open for crude under escort, but not for refined products.",
        "reading": "Crude flows recovered [2]. Refined products lag [3].",
        "stances": [{"n": 2, "stance": "contradicts", "says": "Crude is back near pre-war levels."},
                    {"n": 3, "stance": "supports", "says": "Products are still half of normal."}],
        "gaps": ["Insurance rates", " "],
        "consequences": [
            consequence("Diesel and jet fuel stay scarce in Europe", sources=[3], signposts=[DIESEL_SIGNPOST]),
            consequence("Gulf states build pipelines around the strait", basis="argued", dampening=True),
        ],
    }


def make(api, monkeypatch, hormuz, **body) -> tuple[int, list[dict]]:
    sent = claude_answers(monkeypatch, {READ: first_reading()})
    made = api.post("/api/foresights", json={
        "name": "Strait of Hormuz", "statement": "The Strait of Hormuz stays closed through the winter",
        "kind": "event", "horizon": "months", "note": "I expect the closure to last.", **body}).json()
    assert wait_for(api, made["job_id"])["status"] == "done"
    return made["id"], sent


def page(api, foresight_id: int) -> dict:
    return api.get(f"/api/foresights/{foresight_id}").json()


def ring(found: dict, number: int) -> list[dict]:
    return [node for node in found["nodes"] if node["ring"] == number]


# --- the add-on is found, and leaves the platform alone when it is gone ------------------------------

def test_the_platform_finds_the_add_on_and_its_setting(api):
    meta = api.get("/api/meta").json()
    assert meta["addons"]["foresight"] == {"count": 0, "max_ring": 3, "model_label": "Claude Sonnet 5.5"}
    settings = api.get("/api/settings").json()
    assert any(spec["key"] == "model_foresight" for spec in settings["spec"])
    assert settings["values"]["model_foresight"] == "claude-sonnet-5-5"


def test_without_its_folder_or_with_a_broken_add_on_the_platform_still_works(tmp_path):
    """The proof that the add-on can be taken out: a copy of the backend without its folder, and with an
    add-on that fails to import, starts and answers."""
    root = Path(__file__).resolve().parent.parent
    shutil.copytree(root / "backend", tmp_path / "backend",
                    ignore=shutil.ignore_patterns("__pycache__", "foresight"))
    broken = tmp_path / "backend" / "addons" / "broken"
    broken.mkdir()
    (broken / "__init__.py").write_text("raise RuntimeError('this add-on is broken')\n")
    script = textwrap.dedent("""
        from fastapi.testclient import TestClient
        from backend import addons
        from backend.main import app
        with TestClient(app) as client:
            meta = client.get("/api/meta").json()
            assert meta["addons"] == {}, meta["addons"]
            assert "RuntimeError" in addons.failed["broken"]
            assert client.get("/api/topics").status_code == 200
            assert client.get("/api/stats").status_code == 200
            assert client.get("/api/foresights").status_code == 404
            assert not any(spec["key"] == "model_foresight" for spec in client.get("/api/settings").json()["spec"])
        print("ok")
    """)
    environment = {**os.environ, "NSP_DATA_DIR": str(tmp_path / "data"), "NSP_EMBEDDER": "hash",
                   "ANTHROPIC_API_KEY": "", "PYTHONPATH": str(tmp_path)}
    done = subprocess.run([sys.executable, "-c", script], cwd=tmp_path, env=environment, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0 and done.stdout.strip().endswith("ok"), done.stderr[-2000:]


def test_an_add_on_that_fails_to_start_is_left_out(monkeypatch, job):
    failing = SimpleNamespace(init=lambda: (_ for _ in ()).throw(RuntimeError("no table")),
                              after_scrape=lambda job: (_ for _ in ()).throw(ValueError("oops")))
    monkeypatch.setattr(addons, "loaded", {"failing": failing})
    monkeypatch.setattr(addons, "failed", {})
    assert addons.after_scrape(job) == {} and "failing: ValueError: oops" in job.text()  # the scrape goes on
    addons.init()
    assert addons.loaded == {} and "no table" in addons.failed["failing"] and addons.meta() == {}


# --- reading a signal against the library ----------------------------------------------------------

def test_a_foresight_is_first_found_by_its_name_and_the_names_in_it():
    assert library.first_terms("Strait of Hormuz stays closed", "The Strait of Hormuz stays closed in winter") == [
        "Strait of Hormuz stays closed", "Strait of Hormuz"]
    assert library.first_terms("NATO innovation", "DIANA and the NATO Innovation Fund grow") == [
        "NATO innovation", "NATO", "DIANA", "NATO Innovation Fund"]
    assert library.first_terms("demographic ageing") == ["demographic ageing"]


def test_a_name_too_common_in_the_library_is_left_out_of_the_first_terms(hormuz, monkeypatch):
    monkeypatch.setattr(library, "COMMON_FROM", 0)
    monkeypatch.setattr(library, "COMMON_SHARE", 0.5)
    # the strait is in three of the four items, Qatar in one
    assert library.first_terms("Hormuz and Qatar", "The Strait of Hormuz and Qatar LNG") == [
        "Hormuz and Qatar", "Qatar", "Qatar LNG"]


def test_a_preview_says_what_the_library_has_and_what_reading_it_costs(api, hormuz):
    found = api.post("/api/foresights/preview", json={
        "name": "Strait of Hormuz", "statement": "The strait stays closed", "kind": "event"}).json()
    assert found["matches"] == 3 and found["reading"] == 3 and found["usd"] > 0
    assert found["model_label"] == "Claude Sonnet 5.5"
    assert {item["id"] for item in found["sample"]} == {hormuz["qatar"], hormuz["crude"], hormuz["products"]}
    assert found["sources"][0]["matches"] == 3
    assert not db.scalar("SELECT COUNT(*) FROM foresights")  # nothing was made


def test_a_new_foresight_is_read_against_the_library_and_gets_its_first_ring(api, monkeypatch, hormuz):
    foresight_id, sent = make(api, monkeypatch, hormuz)
    prompt = sent[0]["prompt"]
    assert sent[0]["task"] == READ and sent[0]["stream"] and sent[0]["model"] == "claude-sonnet-5-5"
    assert "Statement: The Strait of Hormuz stays closed through the winter" in prompt
    assert "What the reader knows: I expect the closure to last." in prompt and "Horizon: the next months" in prompt
    # oldest first, each with its source, date and kind
    assert prompt.index("[1] Qatar LNG") < prompt.index("[2] Crude exports") < prompt.index("[3] Refined products")
    assert "Source: Example Institute · " in prompt and "Wind turbines" not in prompt
    assert "likely, highly likely" in sent[0]["system"] and "dampening" in sent[0]["system"]

    found = page(api, foresight_id)
    assert found["standing"] == "partly" and found["restated"].startswith("Hormuz is open for crude")
    assert found["gaps"] == ["Insurance rates"]
    assert found["terms"] == ["Strait of Hormuz"]  # its name and the names in it; Claude adds none
    stances = {source["article_id"]: source["stance"] for source in found["reading_sources"]}
    assert stances == {hormuz["qatar"]: "", hormuz["crude"]: "contradicts", hormuz["products"]: "supports"}
    first = ring(found, 1)
    assert [node["text"] for node in first] == ["Diesel and jet fuel stay scarce in Europe",
                                                "Gulf states build pipelines around the strait"]
    assert first[0]["sources"][0]["article_id"] == hormuz["products"] and first[0]["basis"] == "library"
    assert first[1]["basis"] == "reasoning" and first[1]["dampening"]  # "argued", but no item was named
    assert first[0]["signposts"][0]["text"] == DIESEL_SIGNPOST["text"]
    assert found["cost_usd"] > 0 and found["next"]["reading"]["usd"] > 0
    assert api.get("/api/meta").json()["addons"]["foresight"]["count"] == 1
    card = api.get("/api/foresights").json()[0]
    assert card["consequences"] == 2 and card["rings"] == 1 and card["signposts"] == 1 and card["read"] == 3


def test_without_claude_a_foresight_can_still_be_made_and_filled_by_hand(api, hormuz):
    made = api.post("/api/foresights", json={"name": "Demographic ageing"}).json()
    assert made["job_id"] is None
    assert api.post(f"/api/foresights/{made['id']}/read").status_code == 400  # needs a key
    first = api.post(f"/api/foresights/{made['id']}/nodes", json={"text": "Fewer recruits for the armed forces"})
    second = api.post(f"/api/foresights/{made['id']}/nodes",
                      json={"parent_id": first.json()["id"], "text": "Armies buy more drones"}).json()
    nodes = page(api, made["id"])["nodes"]
    assert [(node["ring"], node["basis"]) for node in nodes] == [(1, "yours"), (2, "yours")]
    api.patch(f"/api/foresight-nodes/{second['id']}", json={"note": "Already visible in Ukraine.", "outcome": "happened"})
    assert page(api, made["id"])["nodes"][1]["note"] == "Already visible in Ukraine."
    api.delete(f"/api/foresight-nodes/{first.json()['id']}")
    assert page(api, made["id"])["nodes"] == []  # what followed from it went with it


def test_a_foresight_from_a_topic_reads_that_topics_items(api, monkeypatch, hormuz):
    topic = api.post("/api/topics", json={"name": "Wind", "terms": ["wind farm"], "by_meaning": False}).json()
    foresight_id, sent = make(api, monkeypatch, hormuz, topic_id=topic["id"])
    assert "Wind turbines" in sent[0]["prompt"] and "Qatar LNG" not in sent[0]["prompt"]
    assert page(api, foresight_id)["terms"] == ["Strait of Hormuz"]  # its own words, though the topic's are used
    assert page(api, foresight_id)["topic"]["name"] == "Wind"
    api.delete(f"/api/topics/{topic['id']}")
    assert page(api, foresight_id)["topic_id"] is None  # back to the whole library


# --- the next rings, and the links between chains ----------------------------------------------------

def test_a_consequence_is_worked_out_further_from_the_items_closest_to_it(api, monkeypatch, hormuz):
    foresight_id, _ = make(api, monkeypatch, hormuz)
    diesel = ring(page(api, foresight_id), 1)[0]
    plan = api.get(f"/api/foresight-nodes/{diesel['id']}/plan").json()
    assert plan["possible"] and plan["ring"] == 2 and plan["usd"] > 0
    sent = claude_answers(monkeypatch, {EXPAND: {"consequences": [
        consequence("Trucking costs rise across Europe", sources=[1], likelihood="highly likely"),
        consequence(" ", sources=[1]),  # an empty one is not kept
    ]}})
    assert wait_for(api, api.post(f"/api/foresight-nodes/{diesel['id']}/expand").json()["job_id"])["status"] == "done"
    prompt = sent[0]["prompt"]
    assert "1. Diesel and jet fuel stay scarce in Europe Why: Because it follows." in prompt
    assert "Already worked out next to it:\n- Gulf states build pipelines" in prompt
    second = ring(page(api, foresight_id), 2)
    assert [(node["text"], node["parent_id"], node["likelihood"]) for node in second] == [
        ("Trucking costs rise across Europe", diesel["id"], "highly likely")]

    claude_answers(monkeypatch, {EXPAND: {"consequences": [consequence("Food prices rise", basis="reasoning")]}})
    wait_for(api, api.post(f"/api/foresight-nodes/{second[0]['id']}/expand").json()["job_id"])
    third = ring(page(api, foresight_id), 3)[0]
    assert api.get(f"/api/foresight-nodes/{third['id']}/plan").json() == {"possible": False, "max_ring": 3}
    assert api.post(f"/api/foresight-nodes/{third['id']}/expand").status_code == 400


def test_links_are_only_kept_between_chains(api, monkeypatch, hormuz):
    foresight_id, _ = make(api, monkeypatch, hormuz)
    diesel, pipelines = ring(page(api, foresight_id), 1)
    claude_answers(monkeypatch, {EXPAND: {"consequences": [consequence("Trucking costs rise across Europe")]}})
    wait_for(api, api.post(f"/api/foresight-nodes/{diesel['id']}/expand").json()["job_id"])
    trucking = ring(page(api, foresight_id), 2)[0]
    sent = claude_answers(monkeypatch, {LINKS: {"links": [
        {"from": trucking["id"], "to": diesel["id"], "effect": "reinforces", "why": "Its own parent."},
        {"from": pipelines["id"], "to": trucking["id"], "effect": "dampens", "why": "More oil reaches  Europe."},
        {"from": 99999, "to": diesel["id"], "effect": "dampens", "why": "Not there."},
    ]}})
    wait_for(api, api.post(f"/api/foresights/{foresight_id}/links").json()["job_id"])
    assert f"C{trucking['id']} (ring 2, chain C{diesel['id']} → C{trucking['id']})" in sent[0]["prompt"]
    assert page(api, foresight_id)["links"] == [
        {"from": pipelines["id"], "to": trucking["id"], "effect": "dampens", "why": "More oil reaches Europe."}]


# --- signposts, and reading again with what arrived since -------------------------------------------

def test_new_items_that_match_a_signpost_are_seen_after_a_scrape(api, monkeypatch, hormuz, job):
    already = save("Diesel shortage in Europe deepens as refined products stay blocked at sea",
                   "Diesel shortage in Europe deepens as refined products stay blocked.", published=days_ago(1))
    embed.embed_pending()
    foresight_id, _ = make(api, monkeypatch, hormuz)
    signpost = ring(page(api, foresight_id), 1)[0]["signposts"][0]
    assert [(hit["article_id"], hit["earlier"]) for hit in signpost["seen"]] == [(already, True)]
    assert ring(page(api, foresight_id), 1)[0]["signs"] == {"for": 0, "against": 0}  # it was there already

    time.sleep(1.1)
    new = save("Diesel shortage in Europe deepens: refined products stay blocked",
               "Diesel shortage in Europe deepens as refined products stay blocked in the strait.",
               published=days_ago(0.1))
    old = save("Diesel shortage in Europe deepened as refined products stayed blocked in 1979",
               "Diesel shortage in Europe deepened as refined products stayed blocked.", published=days_ago(400))
    save("Wind farm output rises", "A wind farm off the Dutch coast produced more power.", published=days_ago(0.1))
    embed.embed_pending()
    assert addons.after_scrape(job) == {"foresight": {"signposts_seen": 1}}
    assert "Foresight: 1 new item matched a signpost (Strait of Hormuz)." in job.text()
    found = page(api, foresight_id)
    diesel = ring(found, 1)[0]
    assert diesel["signs"] == {"for": 1, "against": 0} and found["seen"] == 1 and found["fresh"] == 1
    assert [hit["article_id"] for hit in diesel["signposts"][0]["seen"]] == [new, already]  # newest first
    assert old not in {hit["article_id"] for hit in diesel["signposts"][0]["seen"]}  # an old story is not news
    assert addons.after_scrape(job) == {"foresight": {"signposts_seen": 0}}  # each item is seen once
    api.post(f"/api/foresights/{foresight_id}/visit")
    assert page(api, foresight_id)["fresh"] == 0
    assert watch.matches({"text": "zebra crossing", "terms": []}, [new]) == []


def test_a_re_check_reads_what_arrived_since_and_moves_the_consequences(api, monkeypatch, hormuz):
    foresight_id, _ = make(api, monkeypatch, hormuz)
    found = page(api, foresight_id)
    assert found["next"]["recheck"]["waiting"] == 0 and found["next"]["recheck"]["usd"] == 0
    claude_answers(monkeypatch, {})
    refused = wait_for(api, api.post(f"/api/foresights/{foresight_id}/recheck").json()["job_id"])
    assert refused["status"] == "error" and "Nothing has reached the library" in refused["error"]

    time.sleep(1.1)
    new = save("Tankers attacked in the Strait of Hormuz again", "Two tankers were attacked in the Strait of Hormuz.",
               published=days_ago(0.1))
    embed.embed_pending()
    diesel, pipelines = ring(page(api, foresight_id), 1)
    assert page(api, foresight_id)["next"]["recheck"]["waiting"] == 1
    sent = claude_answers(monkeypatch, {RECHECK: {
        "standing": "borne_out", "restated": "The strait is closing again.",
        "what_changed": "Attacks resumed [1].",
        "updates": [{"id": diesel["id"], "status": "strengthened", "why": "Fewer  tankers sail.", "sources": [1]},
                    {"id": 99999, "status": "happening", "why": "Not there.", "sources": []}],
    }})
    assert wait_for(api, api.post(f"/api/foresights/{foresight_id}/recheck").json()["job_id"])["status"] == "done"
    prompt = sent[0]["prompt"]
    assert "[1] Tankers attacked" in prompt and "Qatar LNG" not in prompt  # only what is new
    assert "Reading: Crude flows recovered. Refined products lag." in prompt  # the old numbers would mislead
    assert f"C{diesel['id']} (ring 1, likely): Diesel and jet fuel stay scarce in Europe Signposts: for: " in prompt
    found = page(api, foresight_id)
    assert found["standing"] == "borne_out" and found["restated"] == "The strait is closing again."
    assert ring(found, 1)[0]["status"] == "strengthened" and ring(found, 1)[0]["status_why"] == "Fewer tankers sail."
    check = found["checks"][0]
    assert check["previous"] == "partly" and check["standing"] == "borne_out" and check["items"] == 1
    assert [source["article_id"] for source in check["sources"]] == [new]
    assert check["changes"] == [{"node_id": diesel["id"], "status": "strengthened", "why": "Fewer tankers sail.",
                                 "sources": [1]}]
    assert found["next"]["recheck"]["waiting"] == 0


def test_starting_over_replaces_what_was_worked_out(api, monkeypatch, hormuz):
    foresight_id, _ = make(api, monkeypatch, hormuz)
    api.post(f"/api/foresights/{foresight_id}/nodes", json={"text": "My own idea"})
    assert len(page(api, foresight_id)["nodes"]) == 3
    claude_answers(monkeypatch, {READ: {**first_reading(), "consequences": [consequence("Only this one")]}})
    wait_for(api, api.post(f"/api/foresights/{foresight_id}/read").json()["job_id"])
    assert [node["text"] for node in page(api, foresight_id)["nodes"]] == ["Only this one"]


def test_one_job_at_a_time_and_a_deleted_foresight_takes_its_rings_along(api, monkeypatch, hormuz):
    foresight_id, _ = make(api, monkeypatch, hormuz)
    from backend.addons.foresight import api as routes

    monkeypatch.setattr(routes, "_job_of", lambda foresight_id: "busy")
    assert api.post(f"/api/foresights/{foresight_id}/links").status_code == 409
    assert api.delete(f"/api/foresights/{foresight_id}").status_code == 409
    monkeypatch.undo()
    assert api.delete(f"/api/foresights/{foresight_id}").json() == {"deleted": True}
    assert db.scalar("SELECT COUNT(*) FROM foresight_nodes") == 0
    assert db.scalar("SELECT COUNT(*) FROM foresight_signposts") == 0
    assert api.get(f"/api/foresights/{foresight_id}").status_code == 404
