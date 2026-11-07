"""Translating items that are not in English: what is asked of Claude, what is stored, what is left alone."""

from __future__ import annotations

import json

import pytest

from backend import config, db
from backend.ai import client as ai
from backend.pipeline import scrape, translate
from backend.pipeline.scrape import scrape_source, store_article
from backend.jobs import JobCancelled
from backend.jobs import JobError
from backend.pipeline.translate import (estimated_cost, is_english, needs_translation, offer, pieces, prices,
                                        translate_article, translate_articles, translate_backlog, translate_one,
                                        waiting_for)
from backend.schemas import Recipe
from backend.search import query
from tests.test_pipeline import add_source, institute
from tests.test_sdk_requests import api_message, fake_api  # noqa: F401  (a fixture)

GERMAN = ("Landgestützte Anti-Schiffs-Waffen verändern die Seekriegführung in der Ostsee grundlegend. Die Marine "
          "muss sich darauf einstellen, dass Küstenbatterien ganze Seegebiete sperren können.\n\n"
          "Für die Bundeswehr bedeutet das neue Anforderungen an Aufklärung, Schutz und Führung. Die Studie "
          "empfiehlt, die Zusammenarbeit mit den Ostseeanrainern auszubauen und gemeinsame Übungen abzuhalten.")
ENGLISH = ("Land-based anti-ship weapons are fundamentally changing naval warfare in the Baltic Sea. The navy "
           "has to be prepared for coastal batteries that can close off whole sea areas.\n\n"
           "For the Bundeswehr this means new demands on reconnaissance, protection and command. The study "
           "recommends that cooperation with the Baltic states is extended and that joint exercises are held.")


def store(title: str, text: str, summary: str = "", language: str = "de", **columns) -> int:
    source = db.row("SELECT id FROM sources LIMIT 1")
    source_id = source["id"] if source else add_source(Recipe(site_name="SWP", homepage="https://example.org"))
    return store_article(source_id, "Publications", {
        "url": f"https://example.org/{abs(hash((title, text)))}", "title": title, "author": "", "published_at": "",
        "summary": summary, "text": text, "image_url": "", "pdf_url": "", "content_type": "report",
        "language": language, "tags": "", "word_count": len(text.split()), "is_partial": False, **columns,
    })


def answer(**fields) -> dict:
    return api_message([{"type": "text", "text": json.dumps(fields)}], "end_turn", "claude-haiku-5-5")


def stored(article_id: int) -> dict:
    return db.row("SELECT * FROM articles WHERE id = ?", (article_id,))


def test_english_is_told_from_other_languages_by_its_common_words():
    assert is_english(ENGLISH) is True
    assert is_english(GERMAN) is False
    assert is_english("Krieg in der Ukraine") is None  # too short to tell: Claude is asked
    shared = "Shared in r/geopolitics by u/someone: https://www.reddit.com/r/geopolitics/comments/1abc/in_the_of/"
    assert is_english(f"{GERMAN}\n\n{shared}") is False  # the words of an address do not count


def test_a_short_text_is_told_by_its_script_and_the_common_words_of_other_languages():
    assert needs_translation(GERMAN) and not needs_translation(ENGLISH)  # long enough for the English rule
    assert needs_translation("Krieg in der Ukraine")  # der and in: German two, English one
    assert needs_translation("De kabinetsformatie loopt vast op de stikstof")
    assert needs_translation("La guerre en Ukraine et les sanctions")
    assert needs_translation("Війна в Україні: що відомо")  # another script
    assert not needs_translation("Ukraine war: latest news")  # no common words at all: taken for English
    assert not needs_translation("Podcast: defence spending\nA short note.")
    assert not needs_translation("LA fires: the state of the city")  # one Spanish-looking word is not enough
    assert not needs_translation("https://www.spiegel.de/politik/die-lage-in-der-ukraine")  # an address is no text
    # English written like headlines has few of the commonest English words, and none of another language's
    # (two items of the owner's library, October 2026)
    hunger = ("Using AI to Fight World Hunger: Averting Crises\nWhat if we could see future hunger sooner? AI-assisted "
              "food security early warning systems help experts analyze more data more quickly to anticipate threats "
              "sooner, and they equip decisionmakers with the insights to help mitigate harm and save lives.")
    assert is_english(hunger * 2) is False and not needs_translation(hunger * 2)
    headlines = ("Read more\n\n- Rare Siberian flying squirrels spotted along Ulsan's Taehwa River Two endangered "
                 "Siberian flying squirrels were found near a Taehwa River walking trail in Ulsan, highlighting the "
                 "former industrial city's ecological restoration.\n\n- Double the cuteness: Korea's first red panda "
                 "twins to meet the public Maru and Marong, Korea's first successfully bred red panda twins, will "
                 "meet visitors Wednesday at Seoul Grand Park.")
    assert not needs_translation(headlines)
    # an English title over a German article, as shared on Reddit
    assert needs_translation("Attack on Starlink terminal: Authorities examine the trail to the Turkish mafia\n" + GERMAN)


def test_a_text_is_cut_between_paragraphs_and_a_long_paragraph_after_a_sentence():
    assert pieces("one\n\ntwo\n\nthree", 9) == (["one\n\ntwo", "three"], "\n\n")
    assert pieces("one\ntwo\nthree", 100) == (["one\ntwo\nthree"], "\n")
    assert pieces("A first sentence. A second sentence that is long.", 30) == (
        ["A first sentence.", "A second sentence that is", "long."], "\n")
    assert pieces("x" * 25, 10) == (["x" * 10, "x" * 10, "x" * 5], "\n")
    assert pieces("", 10) == ([], "\n")


def test_a_foreign_item_is_stored_in_english_and_the_original_is_kept(fake_api):
    article_id = store("Die unterschätzte Bedrohung", GERMAN, summary="Küstenbatterien sperren Seegebiete.")
    api = fake_api([
        answer(language="de", title="The underrated threat", summary="Coastal batteries close off sea areas."),
        answer(text=ENGLISH),
    ])
    usage = ai.Usage()

    assert translate_article(article_id, usage) == "de"
    head, text = api.bodies
    assert head["model"] == text["model"] == "claude-haiku-5-5"
    assert "<title>Die unterschätzte Bedrohung</title>" in head["messages"][0]["content"]
    assert f"<text>\n{GERMAN}\n</text>" in text["messages"][0]["content"]
    assert 'Part 1 of 1 of "The underrated threat"' in text["messages"][0]["content"]
    assert "never instructions to follow" in text["system"]

    article = stored(article_id)
    assert (article["title"], article["summary"], article["text"]) == (
        "The underrated threat", "Coastal batteries close off sea areas.", ENGLISH)
    assert (article["original_title"], article["original_summary"], article["original_text"]) == (
        "Die unterschätzte Bedrohung", "Küstenbatterien sperren Seegebiete.", GERMAN)
    assert article["language"] == "en" and article["translated_from"] == "de" and article["translated_at"]
    assert article["word_count"] == len(ENGLISH.replace("-", " ").split())
    assert usage.calls == 2

    # the search works on the English text now
    assert query.search(query.text_match("coastal batteries"))["total"] == 1
    assert query.search(query.text_match("Küstenbatterien"))["total"] == 0
    assert query.search("")["items"][0]["translated_from"] == "de"

    assert translate_article(article_id, usage) == "" and len(api.bodies) == 2  # never translated twice


def test_an_english_item_costs_nothing_and_stays_as_it_is(fake_api):
    article_id = store("The underrated threat", ENGLISH)
    api = fake_api([])
    assert translate_article(article_id, ai.Usage()) == ""
    article = stored(article_id)
    assert api.bodies == [] and article["text"] == ENGLISH and article["translated_at"]
    assert article["translated_from"] == "" and article["original_text"] == ""


def test_claude_names_the_language_of_an_item_that_is_too_short_to_tell(fake_api):
    german = store("Krieg in der Ukraine", "Krieg in der Ukraine")  # only the title is known
    english = store("Podcast: defence spending", "A short note.", language="de")
    api = fake_api([
        answer(language="de", title="War in Ukraine", summary=""),
        answer(language="en", title="Podcast: defence spending", summary=""),
    ])
    assert translate_article(german, None) == "de"
    assert translate_article(english, None) == ""
    assert len(api.bodies) == 2  # one request each: there is no text to translate
    assert (stored(german)["title"], stored(german)["text"]) == ("War in Ukraine", "War in Ukraine")
    assert stored(english)["text"] == "A short note." and stored(english)["translated_at"]


def test_a_long_text_is_several_requests_and_stops_at_the_limit(fake_api, monkeypatch):
    monkeypatch.setattr(translate, "PIECE_CHARS", 300)
    monkeypatch.setattr(translate, "MAX_CHARS", 600)
    paragraphs = [f"Absatz {number}. " + "Die Marine muss sich darauf einstellen. " * 6 for number in (1, 2, 3)]
    article_id = store("Lange Studie", "\n\n".join(p.strip() for p in paragraphs))
    api = fake_api([answer(language="de", title="Long study", summary=""),
                    answer(text="Paragraph one."), answer(text="Paragraph two.")])
    assert translate_article(article_id, None) == "de"
    assert [("Absatz 1" in b["messages"][0]["content"], "Absatz 2" in b["messages"][0]["content"])
            for b in api.bodies[1:]] == [(True, False), (False, True)]
    text = stored(article_id)["text"].split("\n\n")
    assert text[:2] == ["Paragraph one.", "Paragraph two."]
    assert text[2].startswith("[The translation stops here. The original goes on for another 38 words")
    assert "Absatz 3" in stored(article_id)["original_text"]


def test_an_item_that_cannot_be_translated_is_left_as_it_was(fake_api):
    article_id = store("Die unterschätzte Bedrohung", GERMAN)
    refusal = api_message([], "refusal", "claude-haiku-5-5")
    fake_api([answer(language="de", title="The underrated threat", summary=""), refusal])
    with pytest.raises(ai.AIError, match="declined"):
        translate_article(article_id, None)
    article = stored(article_id)
    assert article["title"] == "Die unterschätzte Bedrohung" and article["text"] == GERMAN
    assert article["translated_at"] == "" and article["language"] == "de"  # so that it is tried again


def test_the_backlog_is_translated_and_stops_when_nothing_gets_through(fake_api, job):
    first = store("Die unterschätzte Bedrohung", GERMAN)
    store("The underrated threat", ENGLISH)
    api = fake_api([answer(language="de", title="The underrated threat", summary=""), answer(text=ENGLISH)])
    source_id = stored(first)["source_id"]
    assert translate_backlog(source_id, job) == {"translated": 1, "already_english": 0, "failed": 0, "left": 0,
                                                 "pending": 1, "too_long": 0}  # the English one was sorted out
    assert job.usage["calls"] == 2 and "Translated 1 of 1 items." in job.text()
    assert translate_backlog(source_id, job)["pending"] == 0 and len(api.bodies) == 2

    for number in range(4):
        store(f"Studie {number}", GERMAN + f" {number}")
    fake_api([])  # every request fails
    with pytest.raises(Exception, match="Stopped translating after three items in a row failed"):
        translate_backlog(source_id, job)


def test_a_scrape_does_not_translate_unless_its_source_says_so(site, job, fake_api):
    api = fake_api([])  # any request would fail the test
    source_id = add_source(institute(site))
    german = store("Die unterschätzte Bedrohung", GERMAN)
    totals = scrape_source(source_id, job, deep=True)
    assert totals["new"] > 0 and "translation" not in totals and api.bodies == []
    assert "Translat" not in job.text()
    assert stored(german)["text"] == GERMAN and not stored(german)["translated_at"]


def test_what_a_stopped_run_has_spent_is_on_record(fake_api, job, monkeypatch):
    monkeypatch.setattr(translate, "PIECE_CHARS", 300)
    article_id = store("Lange Studie", "\n\n".join("Die Marine muss sich darauf einstellen. " * 6 for _ in range(3)))
    fake_api([answer(language="de", title="Long study", summary=""), answer(text="Paragraph one."),
              answer(text="Paragraph two.")])
    checks = iter([None, None, JobCancelled()])  # the run is stopped before the second piece of the text

    def check_cancelled():
        signal = next(checks)
        if signal:
            raise signal

    monkeypatch.setattr(job, "check_cancelled", check_cancelled)
    with pytest.raises(JobCancelled):
        translate_articles([article_id], job, ai.Usage())
    assert job.usage["calls"] == 2 and job.usage["estimated_cost_usd"] > 0  # the title and the first piece
    assert stored(article_id)["title"] == "Lange Studie" and not stored(article_id)["translated_at"]


def test_a_text_that_two_items_share_is_paid_for_once(fake_api, job):
    study = store("Diasporapolitik im Zeitalter der Autokratisierung", GERMAN)
    piece = store("Wie autoritäre Staaten ihre Diasporas instrumentalisieren", GERMAN)  # the same PDF behind it
    api = fake_api([answer(language="de", title="Diaspora policy", summary=""), answer(text=ENGLISH),
                    answer(language="de", title="How authoritarian states use their diasporas", summary="")])
    assert waiting_for(stored(study)["source_id"])["items"] == 2
    result = translate_articles([study, piece], job, ai.Usage())
    assert result["translated"] == 2 and len(api.bodies) == 3  # the second item only needed its title
    assert stored(piece)["text"] == stored(study)["text"] == ENGLISH
    assert stored(piece)["title"] == "How authoritarian states use their diasporas"
    assert stored(piece)["original_text"] == GERMAN


def test_a_run_goes_shortest_first_and_stays_under_what_it_may_cost(fake_api, job):
    report = store("Lange Studie", "\n\n".join([GERMAN] * 12))  # stored first, translated last
    note = store("Kurze Notiz", GERMAN)
    paper = store("The underrated threat", "\n\n".join([ENGLISH] * 12))
    cheap, dear = estimated_cost(len(GERMAN), "claude-haiku-5-5"), estimated_cost(len(GERMAN) * 12, "claude-haiku-5-5")
    config.update({"claude_budget_usd": (cheap + dear) / 2})
    api = fake_api([answer(language="de", title="Short note", summary=""), answer(text=ENGLISH)])
    usage = ai.Usage()
    usage.cost_usd = cheap / 2  # what the fake requests would not add up to

    result = translate_articles([report, note, paper], job, usage)
    assert result == {"translated": 1, "already_english": 1, "failed": 0, "left": 1, "pending": 3}
    assert len(api.bodies) == 2 and "Kurze Notiz" in api.bodies[0]["messages"][0]["content"]
    assert stored(note)["translated_from"] == "de" and stored(paper)["translated_at"]  # English costs nothing
    assert not stored(report)["translated_at"] and stored(report)["title"] == "Lange Studie"
    assert "1 items were not translated" in job.text() and "the most this run may cost" in job.text()
    assert "raise the limit" in job.text()  # this one costs more than the limit by itself

    config.update({"claude_budget_usd": 0})  # no limit
    fake_api([answer(language="de", title="Long study", summary=""), answer(text=ENGLISH)])
    assert translate_articles([report], job, ai.Usage())["translated"] == 1


def test_the_estimate_agrees_with_what_real_runs_cost():
    # Measured in October 2026: a German paper of 23,743 characters with Claude Haiku 5.5, and nine German
    # items with Claude Sonnet 5.5.
    assert estimated_cost(23_743, "claude-haiku-5-5") == pytest.approx(0.0052, rel=0.1)
    sonnet_run = (30_120, 30_597, 767, 225_037, 2_045, 23_743, 29_802, 251, 4_501)
    assert sum(estimated_cost(chars, "claude-sonnet-5-5") for chars in sonnet_run) == pytest.approx(1.52, rel=0.1)
    assert estimated_cost(10**7, "claude-haiku-5-5") == estimated_cost(translate.MAX_CHARS, "claude-haiku-5-5")


def test_the_dashboard_is_told_what_translation_costs_with_the_chosen_model():
    article_id = store("Die unterschätzte Bedrohung", GERMAN)
    store("The underrated threat", ENGLISH)
    source_id = stored(article_id)["source_id"]
    haiku = prices()
    assert haiku["model_label"] == "Claude Haiku 5.5" and haiku["budget_usd"] == 0.5 and haiku["max_minutes"] == 20
    assert haiku["news_per_1000_usd"] == pytest.approx(1.3, rel=0.1)
    assert haiku["papers_per_1000_usd"] == pytest.approx(5.4, rel=0.1)
    assert waiting_for(source_id) == {"items": 1, "usd": round(estimated_cost(len(GERMAN), "claude-haiku-5-5"), 4),
                                      "minutes": 1, "too_long": 0, "max_minutes": 20}

    config.update({"model_translate": "claude-sonnet-5-5"})
    assert prices()["model_label"] == "Claude Sonnet 5.5"
    assert prices()["papers_per_1000_usd"] == pytest.approx(20 * haiku["papers_per_1000_usd"])


def test_a_source_switched_to_translate_does_its_new_items_after_a_scrape(fake_api, job):
    note = store("Kurze Notiz", GERMAN)
    study = store("Lange Studie", "\n\n".join([GERMAN] * 100))  # some 5,000 words: a 23-minute read
    english = store("The underrated threat", ENGLISH)
    db.execute("UPDATE sources SET translate_new = 1")
    source = db.row("SELECT * FROM sources LIMIT 1")
    api = fake_api([answer(language="de", title="Short note", summary=""), answer(text=ENGLISH)])
    totals: dict = {}

    scrape._after_storing(source["id"], source, [note, study, english], job, totals, False, None)

    assert totals["translation"] == {"translated": 1, "already_english": 0, "failed": 0, "left": 0, "pending": 1,
                                     "too_long": 1}
    assert len(api.bodies) == 2 and "Kurze Notiz" in api.bodies[0]["messages"][0]["content"]
    assert stored(note)["title"] == "Short note" and stored(note)["translated_from"] == "de"
    assert stored(english)["translated_at"] and not stored(english)["translated_from"]  # judged once, for nothing
    assert stored(study)["title"] == "Lange Studie" and not stored(study)["translated_at"]  # the button may still
    assert "Translating 1 new item that is not in English (Claude Haiku 5.5). 1 longer than a 20-minute read" \
        in job.text() and job.usage["calls"] == 2
    config.update({"translate_max_minutes": 30})  # the owner's limit for SWP
    assert translate.among_new([study, english]) == ([study], 0)


def test_a_database_from_before_translation_gets_its_columns(site):
    article_id = store("Die unterschätzte Bedrohung", GERMAN)
    db.execute("ALTER TABLE articles DROP COLUMN original_text")
    db.init()
    assert stored(article_id)["original_text"] == "" and stored(article_id)["text"] == GERMAN


def test_the_source_button_does_what_is_not_in_english_and_leaves_out_what_is_too_long(fake_api, job):
    note = store("Kurze Notiz", GERMAN)
    study = store("Lange Studie", "\n\n".join([GERMAN] * 100))  # some 5,000 words: a 23-minute read
    english = store("The underrated threat", ENGLISH)
    video = store("Kabinet valt", "De kabinetsformatie loopt vast op de stikstof.", content_type="video",
                  video_id="abc123")  # becomes English when it is written up, not by translating
    source_id = stored(note)["source_id"]
    assert stored(study)["word_count"] > 20.5 * translate.WORDS_PER_MINUTE

    waiting = waiting_for(source_id)
    assert (waiting["items"], waiting["too_long"], waiting["max_minutes"]) == (1, 1, 20)
    assert stored(english)["translated_at"] and not stored(english)["translated_from"]  # judged once, for nothing
    assert not stored(video)["translated_at"] and not stored(note)["translated_at"]

    api = fake_api([answer(language="de", title="Short note", summary=""), answer(text=ENGLISH)])
    result = translate_backlog(source_id, job)
    assert (result["translated"], result["too_long"]) == (1, 1) and len(api.bodies) == 2
    assert "Kurze Notiz" in api.bodies[0]["messages"][0]["content"]
    assert "1 longer than a 20-minute read is left out" in job.text()
    assert stored(study)["title"] == "Lange Studie" and stored(video)["title"] == "Kabinet valt"

    config.update({"translate_max_minutes": 0})  # no limit
    assert (waiting_for(source_id)["items"], waiting_for(source_id)["too_long"]) == (1, 0)


def test_the_source_button_may_spend_what_it_said_it_costs(fake_api, job, monkeypatch):
    first, second = store("Kurze Notiz", GERMAN), store("Noch eine Notiz", GERMAN + " Zwei.")
    said = estimated_cost(len(GERMAN), "claude-haiku-5-5") + estimated_cost(len(GERMAN) + 6, "claude-haiku-5-5")
    given = []
    monkeypatch.setattr(translate, "translate_articles",
                        lambda ids, job, usage, limit: given.append((ids, limit)) or {"translated": 0})
    fake_api([])

    config.update({"claude_budget_usd": said / 10})  # one run may spend less than the button says
    translate_backlog(stored(first)["source_id"], job)
    assert given[-1][0] == [first, second] and given[-1][1] == pytest.approx(said * translate.MARGIN)
    config.update({"claude_budget_usd": 5})  # more than it says: that limit stays
    translate_backlog(stored(first)["source_id"], job)
    assert given[-1][1] == 5
    config.update({"claude_budget_usd": 0})  # no limit at all
    translate_backlog(stored(first)["source_id"], job)
    assert given[-1][1] == 0


def test_the_reader_offers_to_translate_one_item_whatever_its_length(fake_api, job):
    study = store("Lange Studie", "\n\n".join([GERMAN] * 100))
    english = store("The underrated threat", ENGLISH)
    video = store("Kabinet valt", "De kabinetsformatie loopt vast op de stikstof.", content_type="video",
                  video_id="abc123")
    shown = offer(stored(study))
    assert shown["model_label"] == "Claude Haiku 5.5" and shown["seconds"] > 60
    assert shown["usd"] == round(estimated_cost(len(stored(study)["text"]), "claude-haiku-5-5"), 4)
    assert offer(stored(english)) is None and offer(stored(video)) is None

    api = fake_api([answer(language="de", title="Long study", summary="")] + [answer(text=ENGLISH)] * 40)
    assert translate_one(study, job) == {"translated": 1, "language": "de"}
    assert stored(study)["title"] == "Long study" and stored(study)["translated_from"] == "de"
    assert job.usage["calls"] == len(api.bodies) > 2  # a long text is several requests, all counted
    assert offer(stored(study)) is None  # translated: the reader shows "Show the original" instead
    assert translate_one(study, job)["translated"] == 0 and "translated already" in job.text()
    with pytest.raises(JobError, match="no longer in the library"):
        translate_one(99999, job)
