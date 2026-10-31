"""Hand-picked pages or documents: no listing, just the URLs themselves."""

from __future__ import annotations

from collections.abc import Iterator

from ..registry import Field
from ..schemas import FeedRecipe
from ..util import canonical_url
from .base import Connector, Context, Item, ListPage, connectors


@connectors.register
class SingleConnector(Connector):
    name = "single"
    label = "Single pages / documents"
    description = (
        "Treats the URL itself (an article page or a PDF) as the one item. Use it for a standalone document "
        "that has no listing. Extra URLs can be added, one per line."
    )
    fields = [Field("extra_urls", "Extra URLs", help="More page or PDF URLs, separated by spaces or new lines.")]

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        urls = [feed.url, *feed.opt("extra_urls").split()]
        unique = list(dict.fromkeys(canonical_url(u) for u in urls if u.startswith(("http://", "https://"))))
        yield ListPage([Item(url=u) for u in unique], feed.url, {"urls": len(unique)})
