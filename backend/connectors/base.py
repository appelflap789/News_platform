from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from ..errors import ScrapeError
from ..fetchers import FetchResult, fetchers
from ..registry import Field, Registry
from ..schemas import FeedRecipe
from ..util import truncate


class ConnectorError(ScrapeError):
    """A feed could not be listed (bad selector, not a feed, ...)."""


@dataclass
class Item:
    """One entry found in a listing, before its own page has been opened."""

    url: str
    title: str = ""
    published: str = ""
    summary: str = ""
    author: str = ""
    image_url: str = ""
    content_html: str = ""  # full content, when the listing itself carries it
    tags: list[str] = field(default_factory=list)
    extra: dict[str, str] = field(default_factory=dict)  # the connector's own notes, from listing to reading

    def preview(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "published": self.published,
            "summary": truncate(self.summary, 220),
            "author": self.author,
            "image_url": self.image_url,
            "has_full_content": bool(self.content_html),
        }


@dataclass
class ListPage:
    items: list[Item]
    url: str
    diagnostics: dict = field(default_factory=dict)


class Context:
    """The outside world, as plugins see it. Tests swap this for a fake."""

    def fetch(self, url: str, fetcher: str = "http", **kwargs) -> FetchResult:
        return fetchers.get(fetcher).fetch(url, **kwargs)


class Connector:
    name = ""
    label = ""
    description = ""
    fields: list[Field] = []
    # True when listing entries already contain the whole item, so item pages are never opened.
    inline_content = False
    # True when a listing is strictly newest first (a channel's uploads, a podcast's episodes). An update then
    # stops at the first item it already has: what comes after is older, and was left out on purpose (a first
    # scrape of the newest 20) or is for a deep scrape to fetch.
    newest_first = False
    # False keeps a connector out of what Claude is offered when it analyses a new source.
    for_analysis = True

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        """Yield listing pages, newest first, until the source runs out. The caller decides when to stop."""
        raise NotImplementedError

    def opens_items(self, feed: FeedRecipe) -> bool:
        """Whether a scrape opens every item (`read_item`, or else the extractors on the item's page), or
        stores what the listing said about it."""
        return feed.fetch_detail and not self.inline_content

    def read_item(self, item: Item, feed: FeedRecipe, ctx: Context):
        """Read one item's own page into an `Extracted`. None (the default) leaves that to the extractors."""
        return None

    def page_limit(self, feed: FeedRecipe, deep: bool) -> int:
        """How many listing pages a scrape may walk. 0 (the default) means the limit from Settings."""
        return 0


connectors: Registry[Connector] = Registry("connector")
