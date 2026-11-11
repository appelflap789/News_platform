"""Carnegie Europe, the Brussels centre of the Carnegie Endowment for International Peace (carnegieendowment.org/europe).

Two series are collected, each as a stream:

- **Strategic Europe**, Carnegie Europe's blog (`/europe/strategic-europe/<year>/<month>/<slug>`): short
  commentaries, *Judy Asks* and *Taking the Pulse* roundups, about 90 a year since 2018 (about 250 a year before).
- **Research** (`/europe/research/<year>/<month>/<slug>`): articles, papers and reports by Carnegie Europe's
  scholars, about 20 a year.

The site is a Next.js app. Its listing pages build their lists in the browser: `/europe/research` has no items
in its HTML at all, `/europe/strategic-europe` the six newest, and `?page=2` is the same page again. It has no
RSS feed and its WordPress-style API does not exist. What it does publish is a sitemap (`/sitemap.xml`, an index
of indexes): `posts-0…3.xml` hold every blog post of the Endowment (Strategic Europe among them),
`research-0.xml` all research. The addresses carry year and month, `lastmod` the last edit; the files are not
in date order.

So a stream's first page is what the site shows server-side (the blog's six newest; for research the items on
the Carnegie Europe home page), and the pages after it are the sitemap's addresses for that series, newest
first by the year and month in the address. An update that finds nothing new on the first page stops there and
never downloads the sitemap (about 18 MB in five files); a first or deep scrape goes on into it.

Item pages: title, summary, date and authors in meta tags and JSON-LD (research pages name every author in
`citation_author`; their JSON-LD can leave out the Carnegie scholars), the kind (Commentary, Article, Paper…)
in the first `span.font-mono` of `main`, topics and regions as links in `main`, and the text in the `div.cms-html`
blocks of the first column (`section.order-1`): `payload-richtext` on newer pages, `html-block` on pieces from
before about 2016. Author biographies and the newsletter box sit in the same column, in other divs. Papers have
a *Full Text (PDF)* link; their whole text is on the page as well.
"""

from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Iterator

from ..util import canonical_url, clean, element_text, parse_date
from .base import Context, Extracted, ExtractError, Item, ListPage, Page, SiteScraper, Stream, scrapers

HOME = "https://carnegieendowment.org"
EUROPE = f"{HOME}/europe"
BLOG = f"{EUROPE}/strategic-europe"
RESEARCH = f"{EUROPE}/research"
SITEMAPS = {
    "strategic-europe": f"{HOME}/sitemaps/posts-index.xml",
    "research": f"{HOME}/sitemaps/research-index.xml",
}
PER_PAGE = 10  # sitemap addresses handed to the platform at a time
KEEP_LISTED = 12 * 3600  # seconds a series' sitemap addresses are remembered
SHORT_TEXT = 3000  # characters; a page with less than this and a PDF gets the PDF's text as well
KINDS = {"paper": "paper", "report": "report", "book": "report"}  # the page's kind -> the platform's; else article
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
ENTRY = re.compile(r"<url>\s*<loc>\s*([^<\s]+)\s*</loc>(.*?)</url>", re.S)
LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>")
YEAR_MONTH = re.compile(r"/(\d{4})/(\d{2})/[^/]+$")


@scrapers.register
class CarnegieEurope(SiteScraper):
    name = "carnegieeurope"
    label = "Carnegie Europe"
    homepage = EUROPE
    description = ("Carnegie Europe, the Brussels centre of the Carnegie Endowment for International Peace: the "
                   "Strategic Europe blog and research on the EU, European security, enlargement and democracy.")
    language = "en"
    notes = """\
Built scraper (`backend/scrapers/carnegieeurope.py`).

**Two feeds.** *Strategic Europe* is Carnegie Europe's blog: commentaries, *Judy Asks* and *Taking the Pulse*,
about two a week (roughly 90 a year; it was 250 a year before 2018). *Research* is the centre's articles, papers
and reports, about 20 a year.

**How it finds them.** The site's listing pages build their lists in the browser, so a scraper sees only the
newest few (the blog's six; the research items on the Carnegie Europe home page). That is the first page of
each feed, and enough for a daily update. Everything older comes from the sitemap the site publishes for
crawlers, newest first by the year and month in each address. The sitemap is only downloaded when a scrape goes
past the first page (a first scrape, a deep scrape): about 18 MB, remembered for 12 hours.

**Collected per item.** The kind (Commentary, Article, Paper…), title, authors, date, summary, full text,
picture, topics and regions as tags, and the PDF link for papers.

**Left out.** Carnegie Europe's events, videos, podcasts and the *In the Media* pieces its scholars write for
other papers (only those that live under `/europe/strategic-europe/` or `/europe/research/` are collected).

**How much.** The first scrape takes about 30 items of each feed, two minutes. The whole archive is about 2,500
blog posts back to 2012 and 400 research items back to 2011: a deep scrape of everything takes about an hour.
"""
    streams = [
        Stream("strategic-europe", "Strategic Europe", BLOG),
        Stream("research", "Research", RESEARCH),
    ]
    archive_pages = 400

    def __init__(self) -> None:
        self._listed: dict[str, tuple[float, list[str]]] = {}  # series -> (when read, addresses newest first)

    # -- listing ---------------------------------------------------------------------------------

    def list_pages(self, stream: Stream, ctx: Context) -> Iterator[ListPage]:
        prefix = f"{EUROPE}/{stream.key}/"
        shown_at = BLOG if stream.key == "strategic-europe" else EUROPE
        page = self.open(shown_at, ctx)
        first = _links(page, prefix)
        if first:
            yield ListPage([Item(url=url) for url in first], page.url, {"shown_on_page": len(first)})
        rest = [url for url in self._archive(stream.key, prefix, ctx) if url not in set(first)]
        for start in range(0, len(rest), PER_PAGE):
            chunk = rest[start:start + PER_PAGE]
            yield ListPage([Item(url=url) for url in chunk], SITEMAPS[stream.key],
                           {"addresses_in_sitemap": len(rest), "from": start + 1, "to": start + len(chunk)})

    def _archive(self, series: str, prefix: str, ctx: Context) -> list[str]:
        """Every address of the series in the sitemap, newest first by the year and month in the address."""
        kept = self._listed.get(series)
        if kept and time.time() - kept[0] < KEEP_LISTED:
            return kept[1]
        index = self.fetch(SITEMAPS[series], ctx).text
        found: dict[str, str] = {}  # address -> last edit
        for child in (html.unescape(loc) for loc in LOC.findall(index)):
            for loc, rest in ENTRY.findall(self.fetch(child, ctx).text):
                url = canonical_url(html.unescape(loc))
                if url.startswith(prefix) and YEAR_MONTH.search(url):
                    edited = LASTMOD.search(rest)
                    found[url] = edited.group(1) if edited else ""
        if not found:
            raise ExtractError(f"The sitemap at {SITEMAPS[series]} lists nothing under {prefix}; "
                               f"the site may have changed.")
        addresses = sorted(found, key=lambda url: (YEAR_MONTH.search(url).groups(), found[url]), reverse=True)
        self._listed[series] = (time.time(), addresses)
        return addresses

    # -- one item --------------------------------------------------------------------------------

    def read_item(self, item: Item, stream: Stream, ctx: Context) -> Extracted:
        page = self.open(item.url, ctx)
        soup = page.soup
        main = soup.find("main")
        column = soup.select_one("section.order-1")
        if main is None or column is None:
            raise ExtractError(f"{item.url} is not laid out like a Carnegie page")

        blocks = [block for block in column.select("div.cms-html")
                  if block.parent is not None and block.parent.parent is column]
        text = "\n\n".join(part for part in (element_text(block) for block in blocks) if part)
        pdf_url = next((page.link(link["href"]) for link in main.select("a[href]")
                        if link["href"].lower().split("?")[0].endswith(".pdf") and "pdf" in link.get_text().lower()),
                       "")
        if pdf_url and len(text) < SHORT_TEXT:
            text = "\n\n".join(part for part in (text, self.pdf_text(pdf_url, ctx)) if part)

        data = _json_ld(soup)
        # research pages name every author in citation tags; their JSON-LD can leave out the Carnegie scholars
        authors = [_reversed(clean(meta.get("content"))) for meta in soup.select("meta[name='citation_author']")]
        if not authors:  # blog posts have only the JSON-LD
            authors = [clean(person.get("name")) for person in data.get("author") or [] if isinstance(person, dict)]
        kind_mark = main.select_one("span.font-mono")
        kind = clean(kind_mark.get_text()) if kind_mark else ""
        places = [clean(link.get_text(" ")) for link in main.select("a[href*='/topics/'], a[href*='/regions/']")]
        summary = _meta(soup, "description") or _meta(soup, "og:description")
        if not text:
            raise ExtractError(f"{item.url} has no text on its page")
        return Extracted(
            title=_meta(soup, "og:title"),
            author=", ".join(dict.fromkeys(name for name in authors if name)),
            published=parse_date(_meta(soup, "article:published_time") or data.get("datePublished", "")),
            text=text,
            summary=summary,
            image_url=page.link(_meta(soup, "og:image")),
            pdf_url=pdf_url,
            language="en",
            content_type=KINDS.get(kind.lower(), "article"),
            tags=list(dict.fromkeys(tag for tag in [kind, *places] if tag)),
        )


def _links(page: Page, prefix: str) -> list[str]:
    """The addresses under `prefix` that a page links to, in the order it shows them."""
    found = (canonical_url(page.link(link["href"])) for link in page.soup.select("a[href]"))
    return list(dict.fromkeys(url for url in found if url.startswith(prefix) and YEAR_MONTH.search(url)))


def _meta(soup, name: str) -> str:
    tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
    return clean(tag.get("content")) if tag else ""


def _json_ld(soup) -> dict:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("@type") == "Article":
            return data
    return {}


def _reversed(name: str) -> str:
    """'Bechev, Dimitar' -> 'Dimitar Bechev'."""
    last, _, first = name.partition(",")
    return f"{first.strip()} {last.strip()}".strip() if first else name
