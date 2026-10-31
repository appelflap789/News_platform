from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..connectors import Context
from ..errors import ScrapeError
from ..jobs import Job
from ..pipeline.scrape import preview_feed
from ..registry import Registry
from ..schemas import FeedRecipe, Recipe


@dataclass
class Analysis:
    recipe: Recipe
    previews: dict[str, dict] = field(default_factory=dict)  # feed name -> preview_feed() result or {"error": ...}
    usage: dict = field(default_factory=dict)

    def as_dict(self, analyzer: str, url: str) -> dict:
        return {
            "url": url,
            "analyzer": analyzer,
            "recipe": self.recipe.model_dump(),
            "previews": self.previews,
            "usage": self.usage,
        }


class Analyzer:
    name = ""
    label = ""
    description = ""
    requires_ai = False

    def analyze(self, url: str, hint: str, job: Job, ctx: Context) -> Analysis:
        raise NotImplementedError


analyzers: Registry[Analyzer] = Registry("analyzer")


def feed_key(feed: FeedRecipe) -> str:
    """Identity of a feed's behaviour: two feeds with the same key list the same items."""
    return json.dumps([feed.connector, feed.url, feed.fetcher, sorted(feed.options.items())])


def make_previews(recipe: Recipe, ctx: Context, job: Job, known: dict[str, dict] | None = None) -> dict[str, dict]:
    """A sample of every feed, for the review step of the wizard. `known` (by feed_key) reuses earlier tests."""
    previews: dict[str, dict] = {}
    for feed in recipe.feeds:
        job.check_cancelled()
        if known and feed_key(feed) in known:
            previews[feed.name] = {**known[feed_key(feed)], "feed": feed.name}
            continue
        try:
            previews[feed.name] = preview_feed(feed, ctx)
        except ScrapeError as error:
            previews[feed.name] = {"error": str(error)}
    return previews
