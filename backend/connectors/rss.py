"""RSS and Atom feeds."""

from __future__ import annotations

from collections.abc import Iterator

import feedparser
from bs4 import BeautifulSoup

from ..schemas import FeedRecipe
from ..util import absolutize, canonical_url, clean, html_to_text, parse_date
from ._pagination import PAGINATION_FIELDS, next_page_url
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors


def parse_feed(content: bytes, url: str):
    parsed = feedparser.parse(content)
    if not parsed.entries and (parsed.bozo or not parsed.get("version")):
        raise ConnectorError(f"{url} is not a readable RSS/Atom feed")
    return parsed


def entry_to_item(entry, base_url: str) -> Item | None:
    link = absolutize(base_url, entry.get("link", ""))
    if not link:
        return None
    content_html = ""
    if entry.get("content"):
        content_html = entry.content[0].get("value", "")
    summary_html = entry.get("summary", "")
    return Item(
        url=canonical_url(link),
        title=clean(html_to_text(entry.get("title", ""))),
        published=parse_date(entry.get("published_parsed") or entry.get("updated_parsed")
                             or entry.get("published") or entry.get("updated")),
        summary=clean(html_to_text(summary_html)),
        author=clean(entry.get("author", "")),
        image_url=_entry_image(entry, base_url, content_html or summary_html),
        content_html=content_html,
        tags=[clean(t.get("term", "")) for t in entry.get("tags", []) if t.get("term")],
    )


def _entry_image(entry, base_url: str, html: str) -> str:
    for key in ("media_thumbnail", "media_content"):
        for media in entry.get(key, []) or []:
            if media.get("url") and (key == "media_thumbnail" or "image" in media.get("type", "image")):
                return absolutize(base_url, media["url"])
    for enclosure in entry.get("enclosures", []) or []:
        if "image" in enclosure.get("type", "") and enclosure.get("href"):
            return absolutize(base_url, enclosure["href"])
    if html and "<img" in html:
        image = BeautifulSoup(html, "lxml").find("img", src=True)
        if image:
            return absolutize(base_url, image["src"])
    return ""


@connectors.register
class RssConnector(Connector):
    name = "rss"
    label = "RSS / Atom feed"
    description = (
        "Reads an RSS or Atom feed. The most reliable option when a site offers one. Feeds usually hold only "
        "the latest 10-50 items; WordPress feeds can be paged with pagination=page_param, page_param=paged."
    )
    fields = PAGINATION_FIELDS

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        url = feed.url
        seen: set[str] = set()
        page_index = 0
        while url:
            result = ctx.fetch(url, feed.fetcher, robots=False)
            parsed = parse_feed(result.content, url)
            items = [item for item in (entry_to_item(e, result.url) for e in parsed.entries) if item]
            fresh = [item for item in items if item.url not in seen]
            seen.update(item.url for item in fresh)
            yield ListPage(fresh, result.url, {"entries_in_feed": len(parsed.entries)})
            if not fresh:
                return
            atom_next = next((l.get("href", "") for l in parsed.feed.get("links", []) if l.get("rel") == "next"), "")
            following = next_page_url(feed, result.url, page_index, atom_next=atom_next)
            if following == url:
                return
            url = following
            page_index += 1
