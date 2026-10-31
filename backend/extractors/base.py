from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import ScrapeError
from ..fetchers import FetchResult
from ..registry import Field, Registry


class ExtractError(ScrapeError):
    """An item was downloaded but nothing readable could be taken from it."""


@dataclass
class Extracted:
    title: str = ""
    author: str = ""
    published: str = ""
    text: str = ""
    summary: str = ""
    image_url: str = ""
    pdf_url: str = ""
    language: str = ""
    tags: list[str] = field(default_factory=list)
    content_type: str = ""  # set only when the extractor knows better than the feed (e.g. a PDF)
    # Why the page looks like it keeps its text behind a login or a paywall ('' = it does not); see _walls.py.
    wall: str = ""


class Extractor:
    name = ""
    label = ""
    description = ""
    priority = 100  # lower runs first
    fields: list[Field] = []

    def matches(self, result: FetchResult) -> bool:
        raise NotImplementedError

    def extract(self, result: FetchResult, rules: dict[str, str], ctx) -> Extracted:
        """`rules` is the `article` section of the recipe; `ctx` allows follow-up downloads."""
        raise NotImplementedError


extractors: Registry[Extractor] = Registry("extractor")


def pick(result: FetchResult) -> Extractor:
    for extractor in sorted(extractors.all(), key=lambda e: e.priority):
        if extractor.matches(result):
            return extractor
    raise ExtractError(f"No extractor understands {result.content_type or 'this content'} ({result.url})")


def all_fields() -> list[Field]:
    """Every option any extractor understands (the keys allowed in a recipe's `article` section)."""
    seen: dict[str, Field] = {}
    for extractor in extractors.all():
        for declared in extractor.fields:
            seen.setdefault(declared.key, declared)
    return list(seen.values())
