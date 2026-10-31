"""Site scrapers as sources: the recipe that points a source at a scraper, and adding it to the library."""

from __future__ import annotations

import json

from .. import db
from ..schemas import FeedRecipe, Recipe
from .base import SiteScraper, scrapers


def recipe_for(scraper: SiteScraper) -> Recipe:
    described = scraper.describe()
    return Recipe(
        site_name=described["label"],
        homepage=scraper.homepage,
        description=scraper.description,
        language=scraper.language,
        icon_url=described["icon_url"],
        feeds=[
            FeedRecipe(name=stream.name, connector="scraper", url=stream.url, content_type=stream.content_type,
                       enabled=stream.enabled, fetcher=scraper.fetcher,
                       options={"scraper": scraper.name, "stream": stream.key})
            for stream in scraper.streams
        ],
        structure_report=scraper.notes,
    )


def sources_by_scraper() -> dict[str, int]:
    """Scraper name -> id of the source that uses it."""
    found: dict[str, int] = {}
    for source in db.rows("SELECT id, recipe FROM sources ORDER BY id"):
        for feed in json.loads(source["recipe"]).get("feeds", []):
            if feed.get("connector") == "scraper":
                found.setdefault(feed.get("options", {}).get("scraper", ""), source["id"])
    return found


def describe_all() -> list[dict]:
    added = sources_by_scraper()
    return [{**scraper.describe(), "source_id": added.get(scraper.name)} for scraper in scrapers.all()]


def add_source(scraper: SiteScraper) -> int:
    """Add the scraper to the library as a source and return the source's id."""
    recipe = recipe_for(scraper)
    cursor = db.execute(
        """INSERT INTO sources(name, url, description, language, icon_url, recipe, analyzer, created_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (recipe.site_name, scraper.homepage or scraper.streams[0].url, recipe.description, recipe.language,
         recipe.icon_url, recipe.model_dump_json(), "scraper", db.now()),
    )
    return cursor.lastrowid
