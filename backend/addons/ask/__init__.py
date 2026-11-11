"""Ask the library: a question answered by Claude from the passages of your own items, each claim citing where it
comes from.

An add-on (see backend/addons): everything it is lives in this folder and in `frontend/src/pages/ask`, and deleting
both removes it without breaking anything else. Its tables (store.py) then stay in the library, unused. README,
section "Ask the library", says what it does and what it costs.

* store.py - its tables;
* passages.py - every item split into passages and embedded, free, on this computer;
* find.py - the passages for a question, by meaning and by words;
* answer.py - Claude's answer, with citations;
* api.py - the routes.
"""

from __future__ import annotations

from ... import config, db
from . import answer, passages, store
from .api import router

NAME = "ask"

config.add_setting({
    "key": "model_ask", "group": "Claude", "type": "select", "choices": config.MODEL_CHOICES,
    "default": "claude-sonnet-5-5", "label": "Ask the library model",
    "help": "Answers a question from the passages of your library that match it best. Each question shows its "
            "price before you ask it: about two cents with Claude Sonnet, a twentieth of that with Claude Haiku.",
})
config.add_setting({
    "key": "ask_passages", "group": "Claude", "type": "number", "default": 24,
    "label": "Passages read for a question",
    "help": "How many passages of about a hundred words a question is answered from, at most three from one item. "
            "More gives a fuller answer and costs more.",
})


def init() -> None:
    store.init()


def started() -> None:
    """Once the platform runs: split what is not split yet (the whole library, the first time)."""
    passages.start()


def after_scrape(job) -> dict | None:
    """Free and quick: the splitting itself runs as a job of its own, so the scrape does not wait for it."""
    waiting = passages.pending()
    if waiting:
        passages.start()
        return {"passages_waiting": waiting}
    return None


def meta() -> dict:
    return {"questions": db.scalar("SELECT COUNT(*) FROM ask_questions") or 0,
            "model_label": config.model_label(answer.model())}


__all__ = ["router", "init", "started", "after_scrape", "meta"]
