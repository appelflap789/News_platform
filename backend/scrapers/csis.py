"""CSIS, the Center for Strategic and International Studies (Washington, D.C.).

Everything CSIS writes lives under `/analysis/<slug>`: commentaries, reports, briefs, transcripts, newsletters.
There are two ways to them, and this scraper uses both as two streams.

**Latest** is the first page of https://www.csis.org/analysis: the ten newest items of every kind, each card
with its kind, title, authors, date, summary and a thumbnail. That is as far as the listing goes for a scraper:
the next pages are `?page=N`, and the site's Cloudflare answers those with a bot challenge. Nothing here tries
to get past that.

**Archive** is the site's sitemap, which it publishes for crawlers: an index of pages of 2,000 addresses each,
over 22,000 of them under `/analysis/`. The sitemap gives no usable date (its `lastmod` is the last edit, and
thousands of old pieces were edited in bulk), but it has an order: every kind of content is one stretch in
the order the pieces were made. The analysis addresses come in a few such stretches ("runs": the commentaries,
the reports, a small one in between), each from the 1990s up to now. They are walked from the newest end of
every run at once, each run in proportion to its size, which comes out as roughly newest first. The date, the
title and everything else are then read from the item's own page.

An item's page has the kind, authors and date in a byline block, the date and authors again in `citation_*`
meta tags (the date as month/day/year), the text in one or more `.wysiwyg-wrapper` blocks with figures in
between, and sometimes a PDF under *Available Downloads*. The oldest pieces have no text on the page at all,
only the PDF.
"""

from __future__ import annotations

import html
import re
import time
from collections.abc import Iterator
from weakref import WeakKeyDictionary

from ..fetchers import FetchError
from ..util import canonical_url, clean, element_text, parse_date
from .base import Context, Extracted, ExtractError, Item, ListPage, Page, SiteScraper, Stream, scrapers

LISTING = "https://www.csis.org/analysis"
SITEMAP = "https://www.csis.org/sitemap.xml"
ITEMS = "https://www.csis.org/analysis/"
PER_PAGE = 30  # addresses of the archive handed to the platform at a time: a first scrape takes three such pages
RUN_GAP = 200  # this many other addresses in a row mean the next analysis address starts a new run
KEEP_LISTED = 12 * 3600  # seconds the sitemap is remembered: it changes every few days at most, and is 8 MB
STOP_AFTER = 5  # item pages refused in a row before the run stops asking
SHORT_TEXT = 3000  # characters; a page with less than this and a PDF is an abstract: the PDF is read as well
# The kind in an item's byline -> what the platform calls it. Any other kind is an article.
KINDS = {
    "report": "report",
    "book": "report",
    "brief": "paper",
    "white paper": "paper",
    "transcript": "document",
    "congressional testimony": "document",
    "testimony": "document",
}
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
US_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


@scrapers.register
class Csis(SiteScraper):
    name = "csis"
    label = "CSIS"
    homepage = "https://www.csis.org"
    description = ("The Center for Strategic and International Studies in Washington, D.C.: commentaries, reports, "
                   "briefs and transcripts on defence, security, economics, technology and regions.")
    language = "en"
    notes = """\
Built scraper (`backend/scrapers/csis.py`).

**Two feeds.** *Latest* reads the first page of `/analysis`: the ten newest items of every kind. *Archive* reads
the site's sitemap, which lists over 22,000 analysis pages back to the 1990s.

**Why not the listing's other pages.** `/analysis?page=1` and further are answered with a Cloudflare bot
challenge (HTTP 403) for anything that is not a browser, and the scraper does not try to get past that. The
sitemap is what the site publishes for crawlers, and its robots.txt allows the item pages.

**Order of the archive.** The sitemap carries no publication date, only the order in which pieces were made,
separately for commentaries and for reports. The archive is walked from the newest end of both at once, so it
comes in roughly newest first, 30 items at a time. Each item's real date is read from its own page.

**Collected per item.** Kind (report, commentary, brief, transcript, newsletter…), title, authors, date,
summary, the full text, the programs it belongs to (as tags) and the PDF link when there is one. Where the page
has only an abstract, or no text at all (most pieces from before about 2010), the PDF is read. Some report
PDFs are protected (encrypted) and cannot be read; those items keep their abstract and the link to the PDF.

**Left out.** Events, podcasts, blog posts, press releases (`/news/`) and the people and program pages.

**Keeping up.** The sitemap runs days to weeks behind, and *Latest* shows ten items, about three days of
output. Give this source an update interval of a day or less and nothing is missed.

**How much.** The first scrape takes the ten latest and the newest 90 of the archive: about 100 items, two
minutes. *Update* looks at the newest pages again. *Deep scrape* is only for when you want the back catalogue:
it walks all of it, over 22,000 pages, at one a second about eight hours. It can be stopped and continued; what
is stored is skipped without being opened. If the site starts refusing the scraper, the run stops asking after
five refusals in a row.
"""
    streams = [
        Stream("latest", "Latest", LISTING),
        Stream("archive", "Archive", SITEMAP),
    ]
    archive_pages = 800

    def __init__(self) -> None:
        self._listed: dict[str, tuple[float, list[str]]] = {}  # sitemap address -> (when read, addresses in order)
        self._refused: WeakKeyDictionary[Context, int] = WeakKeyDictionary()  # per run: refusals in a row

    # -- listing ---------------------------------------------------------------------------------

    def list_pages(self, stream: Stream, ctx: Context) -> Iterator[ListPage]:
        if stream.key == "latest":
            yield self._latest(stream, ctx)
            return
        addresses = self._archive(stream.url, ctx)
        for start in range(0, len(addresses), PER_PAGE):
            if self._refused.get(ctx, 0) >= STOP_AFTER:
                return  # csis.org is turning the scraper away: walking on would only ask it again and again
            chunk = addresses[start:start + PER_PAGE]
            yield ListPage([Item(url=url) for url in chunk], stream.url,
                           {"addresses_in_sitemap": len(addresses), "from": start + 1, "to": start + len(chunk)})

    def _latest(self, stream: Stream, ctx: Context) -> ListPage:
        page = self.open(stream.url, ctx)
        cards = page.soup.select("article[class*='-search-listing']")  # report-…, article-…: one class per kind
        items = []
        for card in cards:
            link = card.select_one("h3 a[href]")
            url = canonical_url(page.link(link["href"])) if link else ""
            if not url.startswith(ITEMS):
                continue
            credit = card.select_one(".contributors")
            date = credit.select_one("span.inline-block") if credit else None
            summary = card.select_one(".search-listing--summary")
            image = card.select_one("img[src]")
            kind = _kind(credit)
            items.append(Item(
                url=url,
                title=clean(link.get_text(" ")),
                published=parse_date(clean(date.get_text(" ")).lstrip("—–- ")) if date else "",
                summary=clean(summary.get_text(" ")) if summary else "",
                author=", ".join(_names(credit.select(".contributor--item"))) if credit else "",
                image_url=page.link(image["src"]) if image else "",
                tags=[kind] if kind else [],
            ))
        return ListPage(items, page.url, {"cards_on_page": len(cards), "cards_kept": len(items)})

    def _archive(self, sitemap: str, ctx: Context) -> list[str]:
        """Every analysis address in the sitemap, roughly newest first."""
        kept = self._listed.get(sitemap)
        if kept and time.time() - kept[0] < KEEP_LISTED:
            return kept[1]
        index = self.fetch(sitemap, ctx).text
        children = [html.unescape(loc) for loc in LOC.findall(index)] if "<sitemapindex" in index else []
        listed: list[str] = []  # every address of the sitemap, in its own order
        for child in children:
            listed.extend(html.unescape(loc) for loc in LOC.findall(self.fetch(child, ctx).text))
        if not children:
            listed = [html.unescape(loc) for loc in LOC.findall(index)]
        addresses = newest_first(runs_of(listed))
        if not addresses:
            raise ExtractError(f"The sitemap at {sitemap} lists no pages under {ITEMS}; the site may have changed.")
        self._listed[sitemap] = (time.time(), addresses)
        return addresses

    # -- one item ---------------------------------------------------------------------------------

    def read_item(self, item: Item, stream: Stream, ctx: Context) -> Extracted:
        page = self._open_item(item.url, ctx)
        node = page.soup.select_one("div.node--full")
        if node is None:
            raise ExtractError(f"{item.url} is not laid out like a CSIS analysis page")

        credit = page.soup.select_one(".byline-block .contributors")
        kind = _kind(credit)
        title = page.soup.select_one("h1")
        # one tag per author, but on older pages one tag may hold "A and B"
        authors = [name for meta in page.soup.select("meta[name='citation_author']")
                   for name in re.split(r"\s*,\s*|\s+and\s+", clean(meta.get("content")))]
        if not authors and credit:
            authors = _names(credit.select(".contributor--item"))

        downloads = [page.link(link["href"]) for link in node.select(".downloads-block a[href]")]
        pdf_url = next((url for url in downloads if url.lower().split("?")[0].endswith(".pdf")), "")
        blocks = [block for block in node.select(".text-block .wysiwyg-wrapper")
                  if not block.find_parent(class_=re.compile(r"related|downloads"))]
        text = "\n\n".join(part for part in (element_text(block) for block in blocks) if part)
        if pdf_url and len(text) < SHORT_TEXT:  # an abstract, or (the oldest pieces) nothing at all
            text = "\n\n".join(part for part in (text, self.pdf_text(pdf_url, ctx)) if part)

        programs = _names(node.select(".related-programs-block a[href]"))
        summary = _meta(page, "description") or _meta(page, "og:description")
        return Extracted(
            title=clean(title.get_text(" ")) if title else _meta(page, "og:title"),
            author=", ".join(dict.fromkeys(author for author in authors if author)),
            published=_published(page, credit),
            # an interactive feature has no text on its page and no PDF: what it says of itself is all there is
            text=text or summary,
            summary=summary,
            image_url=page.link(_meta(page, "og:image")),  # the listing's own picture is a 180-pixel thumbnail
            pdf_url=pdf_url,
            language="en",
            content_type=KINDS.get(kind.lower(), "article"),
            tags=[tag for tag in [kind, *programs[:6]] if tag],
        )

    def _open_item(self, url: str, ctx: Context) -> Page:
        """Open an item's page, and keep count of refusals: a site that turns the scraper away again and again
        is left alone for the rest of the run instead of being asked for every remaining page."""
        if self._refused.get(ctx, 0) >= STOP_AFTER:
            raise FetchError(f"csis.org refused the scraper {STOP_AFTER} times in a row, so it is not asked again "
                             f"in this run. Try again later.", refused=True)
        try:
            page = self.open(url, ctx)
        except FetchError as error:
            if error.refused or error.status in (403, 429, 503):
                self._refused[ctx] = self._refused.get(ctx, 0) + 1
            raise
        self._refused[ctx] = 0
        return page


def runs_of(listed: list[str]) -> list[list[str]]:
    """The analysis addresses of the sitemap, as the stretches they come in. Within a stretch, press releases
    and the like are mixed in a few at a time; between stretches lie thousands of events, podcasts or blogs."""
    runs: list[list[str]] = []
    current: list[str] = []
    others = 0
    seen: set[str] = set()
    for address in listed:
        if not address.startswith(ITEMS) or address == ITEMS:
            others += 1
            continue
        if others >= RUN_GAP and current:
            runs.append(current)
            current = []
        others = 0
        url = canonical_url(address)
        if url not in seen:
            seen.add(url)
            current.append(url)
    if current:
        runs.append(current)
    return runs


def newest_first(runs: list[list[str]]) -> list[str]:
    """One list from the newest end of every run, each run taken in proportion to its size: when a tenth of the
    commentaries has been taken, so has a tenth of the reports."""
    taken = [0] * len(runs)
    merged: list[str] = []
    for _ in range(sum(len(run) for run in runs)):
        run = min((index for index in range(len(runs)) if taken[index] < len(runs[index])),
                  key=lambda index: (taken[index] / len(runs[index]), -len(runs[index])))
        taken[run] += 1
        merged.append(runs[run][-taken[run]])
    return merged


def _kind(credit) -> str:
    """'Report', 'Commentary', 'Transcript': the words a byline starts with, before 'by' or the date."""
    line = credit.find("p") if credit else None
    first = next((clean(str(part)) for part in (line or credit or []) if isinstance(part, str) and clean(part)), "")
    return re.sub(r"\s+by$", "", first, flags=re.I).strip(" —–-")


def _names(elements) -> list[str]:
    """The text of each element, once each; a list of three authors is written 'A,' 'B,' 'and' 'C'."""
    names = (clean(element.get_text(" ")).rstrip(", ") for element in elements)
    return list(dict.fromkeys(name for name in names if name))


def _meta(page: Page, key: str) -> str:
    found = page.soup.find("meta", attrs={"property": key}) or page.soup.find("meta", attrs={"name": key})
    return clean(found.get("content")) if found else ""


def _published(page: Page, credit) -> str:
    """The date in the citation tag is American, month first ('Fri, 10/09/2026 - 12:00' is 9 October); read as
    a day-first date it lands in another month, so it is taken apart here. Failing that, the byline's date."""
    found = US_DATE.search(_meta(page, "citation_publication_date"))
    if found:
        month, day, year = (int(part) for part in found.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}T00:00:00Z"
    said = clean(credit.get_text(" ")) if credit else ""
    return parse_date(re.split(r"Published|—", said)[-1].strip()) if said else ""
