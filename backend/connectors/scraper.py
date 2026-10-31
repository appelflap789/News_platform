"""Runs a site scraper (a file in `backend/scrapers/`) as a feed."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from ..errors import ScrapeError
from ..registry import Field
from ..schemas import FeedRecipe
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors


@connectors.register
class ScraperConnector(Connector):
    name = "scraper"
    label = "Built scraper"
    description = "Runs a scraper that was written for one specific site (a file in backend/scrapers/)."
    fields = [
        Field("scraper", "Scraper", help="Name of the scraper, e.g. 'clingendael'."),
        Field("stream", "Stream", help="Which of the scraper's streams this feed reads. Empty = its first."),
    ]
    for_analysis = False

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        scraper, stream = self._resolve(feed)
        pages = scraper.list_pages(stream, ctx)
        seen: set[str] = set()
        while True:
            try:
                page = next(pages)
            except StopIteration:
                return
            except ScrapeError:
                raise
            except Exception as error:  # the site changed under code that expected its old shape
                raise ConnectorError(f"The scraper '{scraper.name}' failed while listing "
                                     f"({type(error).__name__}: {error})") from error
            fresh = [item for item in page.items if item.url not in seen]
            seen.update(item.url for item in fresh)
            yield ListPage(fresh, page.url, page.diagnostics)
            if not fresh:  # a site repeating its last page must not loop forever
                return

    def read_item(self, item: Item, feed: FeedRecipe, ctx: Context):
        scraper, stream = self._resolve(feed)
        try:
            return scraper.read_item(item, stream, ctx)
        except ScrapeError:
            raise
        except Exception as error:  # one odd page must cost one item, not the whole scrape
            raise ConnectorError(f"The scraper '{scraper.name}' could not read this page "
                                 f"({type(error).__name__}: {error})") from error

    def page_limit(self, feed: FeedRecipe, deep: bool) -> int:
        return self._resolve(feed)[0].archive_pages if deep else 0

    @staticmethod
    def _resolve(feed: FeedRecipe):
        from ..scrapers import scrapers  # imported late: the scrapers package builds on this one

        name = feed.opt("scraper")
        if name not in scrapers.names():
            raise ConnectorError(
                f"There is no scraper called '{name}' in backend/scrapers/ "
                f"(available: {', '.join(scrapers.names()) or 'none'}). If it was just written, restart the platform."
            )
        scraper = scrapers.get(name)
        # the feed's address wins over the one in the code, so a listing can be re-pointed from the recipe editor
        return scraper, replace(scraper.stream(feed.opt("stream")), url=feed.url)
