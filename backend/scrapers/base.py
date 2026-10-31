from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..connectors.base import Context, Item, ListPage
from ..errors import ScrapeError
from ..extractors import Extracted, ExtractError, pick
from ..fetchers import FetchResult
from ..registry import Registry
from ..util import absolutize

__all__ = ["Context", "ExtractError", "Extracted", "Item", "ListPage", "Page", "SiteScraper", "Stream", "scrapers"]


@dataclass(frozen=True)
class Stream:
    """One stream of items a site offers ('Publications', 'News'). It becomes one feed of the source."""

    key: str
    name: str
    url: str  # where its listing starts
    content_type: str = "article"  # one of schemas.CONTENT_TYPES; `read_item` may refine a generic type per item
    enabled: bool = True


@dataclass
class Page:
    """A downloaded HTML page."""

    url: str  # final URL after redirects
    soup: BeautifulSoup

    def link(self, href: str | None) -> str:
        """An href found on this page as a full URL ('' for empty, mailto:, javascript: and the like)."""
        return absolutize(self.url, href)


class SiteScraper:
    """A scraper written for one specific site.

    The general connectors work from a recipe of CSS selectors. A site scraper is plain Python instead, so it
    can do whatever the site needs: combine what the listing says with what the item page says, call an API,
    skip the kinds of items that are not wanted, read the report behind a download button.

    Subclass it in a new file in this folder, fill in the attributes, implement `list_pages` and usually
    `read_item`, and decorate the class with `@scrapers.register`. `CLAUDE.md` in the project root describes
    the whole routine, and `clingendael.py` is the worked example.
    """

    name = ""  # identifier; by convention the same as the file name
    label = ""  # name of the source in the dashboard
    homepage = ""
    description = ""
    language = ""  # main language of the site, e.g. "en"
    icon_url = ""  # empty = the homepage's /favicon.ico
    notes = ""  # Markdown for the source's Structure tab: how the site is built, what is and is not collected
    streams: list[Stream] = []
    fetcher = "http"
    # Listing pages a deep scrape may walk. Set it above the size of the archive; 0 = the limit from Settings.
    archive_pages = 0

    def list_pages(self, stream: Stream, ctx: Context) -> Iterator[ListPage]:
        """Yield the listing page by page, newest first, until it runs out.

        The scrape stops walking at the first page that yields no items, so a page whose items were all
        filtered out must be skipped, not yielded empty.
        """
        raise NotImplementedError

    def read_item(self, item: Item, stream: Stream, ctx: Context) -> Extracted | None:
        """Open one item and return what its page says. What the listing already said (title, author, date,
        summary) takes precedence when both have it. None = let the platform's extractors read the page."""
        return None

    # -- helpers for subclasses ----------------------------------------------------------

    def fetch(self, url: str, ctx: Context) -> FetchResult:
        return ctx.fetch(url, self.fetcher)

    def open(self, url: str, ctx: Context) -> Page:
        """Download an HTML page and parse it."""
        result = self.fetch(url, ctx)
        if not result.is_html:
            raise ExtractError(f"Expected a web page at {result.url}, got {result.content_type or 'something else'}")
        return Page(result.url, BeautifulSoup(result.text, "lxml"))

    def extract(self, url: str, ctx: Context, **rules: str) -> Extracted:
        """Read an item the way a recipe would: automatic main-text detection, plus the selectors given as
        `rules` (body_selector, date_selector, ... - the `article` options of the recipe reference)."""
        result = self.fetch(url, ctx)
        return pick(result).extract(result, rules, ctx)

    def pdf_text(self, url: str, ctx: Context) -> str:
        """The text of a PDF, or '' when it cannot be downloaded or has no text layer."""
        from ..extractors.pdf_document import pdf_text

        try:
            result = self.fetch(url, ctx)
            return pdf_text(result.content, url)[0] if result.is_pdf else ""
        except ScrapeError:
            return ""

    # -- used by the platform --------------------------------------------------------------

    def stream(self, key: str) -> Stream:
        """The stream with this key; an empty key means the first one."""
        for stream in self.streams:
            if stream.key == key or not key:
                return stream
        raise ScrapeError(f"The scraper '{self.name}' has no stream '{key}' "
                          f"(it has: {', '.join(s.key for s in self.streams) or 'none'})")

    def describe(self) -> dict:
        return {
            "name": self.name,
            "label": self.label or self.name,
            "homepage": self.homepage,
            "description": self.description,
            "icon_url": self.icon_url or (urljoin(self.homepage, "/favicon.ico") if self.homepage else ""),
            "streams": [{"key": s.key, "name": s.name, "content_type": s.content_type, "enabled": s.enabled}
                        for s in self.streams],
        }


scrapers: Registry[SiteScraper] = Registry("scraper")
