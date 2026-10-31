"""Ask Claude to turn a topic name into search terms (synonyms, translations, related concepts)."""

from __future__ import annotations

from .. import config, db
from ..ai import client as ai

SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string", "description": "One sentence saying what this topic covers."},
        "required_any": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Names of which at least one MUST appear. Only for topics about a specific company, "
                           "person, product, programme or place; empty for broad subjects.",
        },
        "terms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Words and short phrases that signal the topic.",
        },
    },
    "required": ["description", "required_any", "terms"],
    "additionalProperties": False,
}

SYSTEM = """You help build saved searches for a personal library of scraped news, reports and papers.

Given a topic, produce the terms a full-text search should look for. How the search works:
- A single word matches as a prefix: "drone" also finds "drones" and "droneaanval". So give the stem once and \
do not list plurals. A phrase of several words matches only when those words appear next to each other.
- An article matches when it contains at least one of `terms` and, if `required_any` is not empty, at least \
one of those as well. Articles that mention more terms, or mention them in the title, rank higher.

For `terms`, give 10 to 25 entries: the topic's own words, synonyms, abbreviations and closely related \
technical terms, in English. Translations only into the other languages listed below, if any: those are the \
languages items in the library are actually written in, so a term in any other language would match nothing. \
Prefer specific terms. Leave out words so general that they would match unrelated articles (for example \
"technology", "government", "new").

Use `required_any` only when the topic is about a named entity. For "Anduril drone innovation", `required_any` \
is ["Anduril"] and `terms` covers drones and innovation; for "climate change", `required_any` is empty."""


SHARE = 0.05  # a language counts when at least this share of the library is written in it ...
MIN_ITEMS = 10  # ... and at least this many items


def library_languages() -> list[str]:
    """The languages the library's items are written in, as the search sees them, the commonest first. A
    translated item counts as English (its English text is what is searched), and so does an item whose page
    claims another language but whose text is English: sites label their English pages "pl" or "ko". A
    language with only a stray item or two does not count."""
    from ..pipeline.translate import is_english

    counts: dict[str, int] = {}
    for row in db.rows("SELECT language, translated_from, title, summary, SUBSTR(text, 1, 3000) AS text FROM articles"):
        language = "en" if row["translated_from"] else (row["language"] or "")[:2].lower()
        if language not in ("", "en") and is_english(f"{row['title']}\n{row['summary']}\n{row['text']}"):
            language = "en"
        if language:
            counts[language] = counts.get(language, 0) + 1
    total = sum(counts.values())
    found = [language for language, count in sorted(counts.items(), key=lambda kv: -kv[1])
             if count >= MIN_ITEMS and count / total >= SHARE]
    return ["en", *[language for language in found if language != "en"]][:5]


def expand_topic(name: str, usage: ai.Usage | None = None) -> dict:
    others = library_languages()[1:]
    languages = (", ".join(others) + " (besides English)") if others else "only English: give no translations"
    result = ai.structured(
        model=str(config.get("model_topics")),
        system=SYSTEM,
        prompt=f"Topic: {name}\nLanguages of the library: {languages}",
        schema=SCHEMA,
        task="expand a topic into search terms",
        effort="low",
        usage=usage,
    )
    return {
        "description": result.get("description", "").strip(),
        "required_any": _tidy(result.get("required_any", [])),
        "terms": _tidy(result.get("terms", [])),
    }


def _tidy(terms: list) -> list[str]:
    cleaned = [" ".join(str(t).split()) for t in terms]
    return list(dict.fromkeys(t for t in cleaned if t))
