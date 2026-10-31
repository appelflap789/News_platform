"""The recipe: the description of a source that Claude writes and the scraper executes.

A recipe is plain data. It names plugins (connector, fetcher) and gives them
options, so a new plugin never needs a schema change here.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

CONTENT_TYPES = ["article", "news", "report", "paper", "post", "document", "video", "podcast", "other"]


def clean_options(options) -> dict[str, str]:
    """Options are always strings; '' and None mean 'not set' and are dropped."""
    cleaned: dict[str, str] = {}
    for key, value in (options or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        value = str(value).strip()
        if value:
            cleaned[str(key)] = value
    return cleaned


class FeedRecipe(BaseModel):
    """One stream of items inside a source, e.g. 'Publications' or 'News (RSS)'."""

    model_config = ConfigDict(extra="ignore")

    name: str
    connector: str
    url: str
    content_type: str = "article"
    enabled: bool = True
    fetch_detail: bool = True
    fetcher: str = "http"
    options: dict[str, str] = Field(default_factory=dict)

    normalise_options = field_validator("options", mode="before")(clean_options)

    def opt(self, key: str, default: str = "") -> str:
        return self.options.get(key, default)

    def opt_int(self, key: str, default: int) -> int:
        try:
            return int(float(self.options[key]))
        except (KeyError, ValueError):
            return default


class Recipe(BaseModel):
    """Everything the platform needs to scrape one source."""

    model_config = ConfigDict(extra="ignore")

    version: int = 1
    site_name: str
    homepage: str = ""
    description: str = ""
    language: str = ""
    icon_url: str = ""
    feeds: list[FeedRecipe] = Field(default_factory=list)
    article: dict[str, str] = Field(default_factory=dict)
    structure_report: str = ""

    normalise_article = field_validator("article", mode="before")(clean_options)


def validate_recipe(recipe: Recipe) -> None:
    """Checks a schema cannot express. Raises ValueError with a message a person (or Claude) can act on."""
    from .connectors import connectors
    from .fetchers import fetchers

    problems: list[str] = []
    if not recipe.site_name.strip():
        problems.append("site_name is empty")
    seen: set[str] = set()
    for feed in recipe.feeds:
        label = f"feed '{feed.name}'"
        if not feed.name.strip():
            problems.append("a feed has no name")
        if feed.name in seen:
            problems.append(f"{label}: feed names must be unique")
        seen.add(feed.name)
        if feed.connector not in connectors.names():
            problems.append(f"{label}: unknown connector '{feed.connector}' (available: {', '.join(connectors.names())})")
        else:
            known = {f.key for f in connectors.get(feed.connector).fields}
            unknown = sorted(set(feed.options) - known)
            if unknown:
                problems.append(
                    f"{label}: connector '{feed.connector}' does not use option(s) {', '.join(unknown)}"
                    f" (it uses: {', '.join(sorted(known)) or 'none'})"
                )
        if feed.fetcher not in fetchers.names():
            problems.append(f"{label}: unknown fetcher '{feed.fetcher}'")
        if urlsplit(feed.url).scheme not in ("http", "https"):
            problems.append(f"{label}: url must start with http:// or https://")
        if feed.content_type not in CONTENT_TYPES:
            problems.append(f"{label}: content_type must be one of {', '.join(CONTENT_TYPES)}")
    if problems:
        raise ValueError("; ".join(problems))
