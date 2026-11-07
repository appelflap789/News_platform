"""Foresight: a trend, a weak signal or an event, read against the library and worked out into its first, second
and third order consequences, with signposts the platform watches for after every scrape.

An add-on (see backend/addons): everything it is lives in this folder and in `frontend/src/pages/foresight`,
and deleting both removes it without breaking anything else. Its tables (store.py) then stay in the library,
unused. README, section "Foresight", says what it does and what it costs; FORESIGHT.md is the design it was
built from.

* store.py - its tables;
* library.py - what the library has on a foresight, found like a topic's items;
* think.py - the four Claude steps (read, expand, links, re-check), each planned and priced before it is sent;
* watch.py - matching new items to the signposts, free;
* api.py - the routes.
"""

from __future__ import annotations

from ... import config, db
from . import store, think, watch
from .api import router

NAME = "foresight"


def init() -> None:
    store.init()


def after_scrape(job) -> dict | None:
    return watch.after_scrape(job)


def meta() -> dict:
    """What the dashboard needs: that foresight is there, how many there are, and how deep they go."""
    return {"count": db.scalar("SELECT COUNT(*) FROM foresights") or 0, "max_ring": think.MAX_RING,
            "model_label": config.model_label(think.model())}


__all__ = ["router", "init", "after_scrape", "meta"]
