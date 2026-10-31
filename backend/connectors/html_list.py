"""HTML listing pages (news overviews, publication archives, search results) read with CSS selectors."""

from __future__ import annotations

from collections.abc import Iterator

from bs4 import BeautifulSoup, Tag

from ..dom import date_of, image_src, select, select_one
from ..registry import Field
from ..schemas import FeedRecipe
from ..util import absolutize, canonical_url, clean
from ._pagination import PAGINATION_FIELDS, next_page_url
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors


@connectors.register
class HtmlListConnector(Connector):
    name = "html_list"
    label = "HTML listing page"
    description = (
        "Reads a page that lists items (a news overview, a publications archive) using CSS selectors, and can "
        "walk through its pages. Use it when there is no feed, or when the feed lacks the archive."
    )
    fields = [
        Field("item_selector", "Item selector",
              help="CSS selector matching ONE element per listed item (the card / row / <article>)."),
        Field("link_selector", "Link selector",
              help="Inside an item: selector of the <a> to the item's page. Empty = the item itself if it is an "
                   "<a>, otherwise its first link."),
        Field("title_selector", "Title selector", help="Inside an item: the title element. Empty = the link text."),
        Field("date_selector", "Date selector",
              help="Inside an item: the date element (a <time datetime> works best). Empty = none."),
        Field("summary_selector", "Summary selector", help="Inside an item: teaser text. Empty = none."),
        Field("image_selector", "Image selector", help="Inside an item: the <img>. Empty = the first image."),
        *PAGINATION_FIELDS,
    ]

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        if not feed.opt("item_selector"):
            raise ConnectorError("html_list needs an item_selector")
        url = feed.url
        seen: set[str] = set()
        page_index = 0
        while url:
            result = ctx.fetch(url, feed.fetcher)
            soup = BeautifulSoup(result.text, "lxml")
            items, diagnostics = self._parse(soup, result.url, feed)
            fresh = [item for item in items if item.url not in seen]
            seen.update(item.url for item in fresh)
            following = next_page_url(feed, result.url, page_index, soup)
            diagnostics["next_page_url"] = following
            yield ListPage(fresh, result.url, diagnostics)
            if not fresh or following == url:  # a site repeating its last page must not loop forever
                return
            url = following
            page_index += 1

    def _parse(self, soup: BeautifulSoup, base_url: str, feed: FeedRecipe) -> tuple[list[Item], dict]:
        nodes = select(soup, feed.opt("item_selector"), "item_selector")
        items: list[Item] = []
        without_link = 0
        for node in nodes:
            link = self._link(node, feed)
            href = absolutize(base_url, link.get("href")) if link is not None else ""
            if not href:
                without_link += 1
                continue
            title_selector = feed.opt("title_selector")
            title_node = select_one(node, title_selector, "title_selector") if title_selector else None
            title = clean((title_node or link).get_text(" ")) or clean(link.get("title") or link.get("aria-label"))
            date_selector = feed.opt("date_selector")
            summary_selector = feed.opt("summary_selector")
            image_selector = feed.opt("image_selector")
            summary_node = select_one(node, summary_selector, "summary_selector") if summary_selector else None
            image_node = select_one(node, image_selector, "image_selector") if image_selector else node.find("img")
            items.append(Item(
                url=canonical_url(href),
                title=title,
                published=date_of(select_one(node, date_selector, "date_selector")) if date_selector else "",
                summary=clean(summary_node.get_text(" ")) if summary_node else "",
                image_url=image_src(image_node, base_url),
            ))
        unique: dict[str, Item] = {}
        for item in items:
            unique.setdefault(item.url, item)
        diagnostics = {
            "elements_matching_item_selector": len(nodes),
            "items_without_a_link": without_link,
            "items_without_a_title": sum(1 for item in unique.values() if not item.title),
            "items_with_a_date": sum(1 for item in unique.values() if item.published),
        }
        return list(unique.values()), diagnostics

    @staticmethod
    def _link(node: Tag, feed: FeedRecipe) -> Tag | None:
        selector = feed.opt("link_selector")
        if selector:
            return select_one(node, selector, "link_selector")
        if node.name == "a" and node.get("href"):
            return node
        return node.find("a", href=True)
