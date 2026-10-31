"""XML sitemaps: every URL a site publishes, filtered down to the ones that are articles."""

from __future__ import annotations

import gzip
import re
from collections.abc import Iterator

from bs4 import BeautifulSoup

from ..registry import Field
from ..schemas import FeedRecipe
from ..util import canonical_url, clean, parse_date
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors

PAGE_SIZE = 50
MAX_CHILD_SITEMAPS = 30


def _regex(pattern: str, what: str) -> re.Pattern | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as error:
        raise ConnectorError(f"{what} '{pattern}' is not a valid regular expression: {error}") from error


@connectors.register
class SitemapConnector(Connector):
    name = "sitemap"
    label = "XML sitemap"
    description = (
        "Lists URLs from a sitemap.xml (or sitemap index). A fallback for sites with neither a feed nor a usable "
        "listing page. Gives only URLs and dates, so every item page is opened. Always set url_pattern, "
        "otherwise every page of the site is treated as an article."
    )
    fields = [
        Field("url_pattern", "URL pattern",
              help="Regular expression an item URL must match, e.g. '/publications?/[^/]+/?$'."),
        Field("exclude_pattern", "Exclude pattern", help="Regular expression of URLs to skip."),
        Field("sitemap_pattern", "Child sitemap pattern",
              help="For a sitemap index: regular expression choosing which child sitemaps to read, e.g. 'post-sitemap'."),
    ]

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        include = _regex(feed.opt("url_pattern"), "url_pattern")
        exclude = _regex(feed.opt("exclude_pattern"), "exclude_pattern")
        child_filter = _regex(feed.opt("sitemap_pattern"), "sitemap_pattern")

        queue = [feed.url]
        visited: set[str] = set()
        seen: set[str] = set()
        while queue:
            sitemap_url = queue.pop(0)
            if sitemap_url in visited or len(visited) >= MAX_CHILD_SITEMAPS:
                continue
            visited.add(sitemap_url)
            soup = self._load(sitemap_url, feed, ctx)

            children = [(clean(s.loc.get_text()), parse_date(s.lastmod.get_text() if s.lastmod else ""))
                        for s in soup.find_all("sitemap") if s.loc]
            if children:
                children.sort(key=lambda child: child[1], reverse=True)
                queue.extend(u for u, _ in children if not child_filter or child_filter.search(u))
                continue

            entries = soup.find_all("url")
            if not entries and not soup.find("urlset"):
                raise ConnectorError(f"{sitemap_url} is not a sitemap")
            items: list[Item] = []
            for entry in entries:
                if not entry.loc:
                    continue
                url = canonical_url(clean(entry.loc.get_text()))
                if url in seen or (include and not include.search(url)) or (exclude and exclude.search(url)):
                    continue
                seen.add(url)
                news_title = entry.find("news:title") or entry.find("title")
                news_date = entry.find("news:publication_date") or entry.find("publication_date")
                image = entry.find("image:loc")
                items.append(Item(
                    url=url,
                    title=clean(news_title.get_text()) if news_title else "",
                    published=parse_date((news_date or entry.lastmod).get_text() if (news_date or entry.lastmod) else ""),
                    image_url=clean(image.get_text()) if image else "",
                ))
            items.sort(key=lambda item: item.published, reverse=True)
            diagnostics = {"urls_in_sitemap": len(entries), "urls_matching": len(items)}
            if not items:
                yield ListPage([], sitemap_url, diagnostics)
            for start in range(0, len(items), PAGE_SIZE):
                yield ListPage(items[start:start + PAGE_SIZE], sitemap_url, diagnostics)

    @staticmethod
    def _load(url: str, feed: FeedRecipe, ctx: Context) -> BeautifulSoup:
        result = ctx.fetch(url, feed.fetcher)
        content = result.content
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return BeautifulSoup(content, "xml")
