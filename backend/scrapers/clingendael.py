"""Clingendael, the Netherlands Institute of International Relations.

https://www.clingendael.org/publications lists every publication, twelve cards a page, newest first, with
`?page=N` counting from 0. A card gives the category, title, authors and a thumbnail; the publication's own
page adds the date, the "In short" takeaways, the text, and for reports and policy briefs a button to the PDF.

Publication pages come in two layouts that differ in the block above the text: the usual one
(`.node-title`, with the date in `.top-wrapper .date`) and a "hero" one with a background image
(`.block--hero`, with category and date as two spans in `.head`). Below that block they are the same.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

from ..util import canonical_url, clean, element_text, parse_date, set_query_param
from .base import Context, Extracted, ExtractError, Item, ListPage, SiteScraper, Stream, scrapers

LISTING = "https://www.clingendael.org/publications"
# Category on the card -> what the platform calls it. Categories that are not listed here are skipped:
# podcasts and multimedia have nothing to read.
CATEGORIES = {
    "Reports and papers": "report",
    "Policy briefs": "paper",
    "Articles": "article",
    "Op-ed": "article",
    "Alerts": "article",
}
DUTCH = re.compile(r"\b(de|het|een|van|en|voor|niet|met|zijn|dat|op|aan)\b", re.I)
ENGLISH = re.compile(r"\b(the|of|and|to|in|for|is|that|with|on|as|are)\b", re.I)


@scrapers.register
class Clingendael(SiteScraper):
    name = "clingendael"
    label = "Clingendael"
    homepage = "https://www.clingendael.org"
    description = ("Clingendael, the Netherlands Institute of International Relations: reports, policy briefs "
                   "and articles on security, Europe, conflict and geopolitics.")
    language = "en"
    notes = """\
Built scraper (`backend/scrapers/clingendael.py`).

**Listing.** `/publications`, twelve cards a page, newest first, `?page=N` from 0; over 430 pages. Each card
carries the category, title, authors and a thumbnail.

**Collected.** Reports and papers, policy briefs, articles, op-eds and alerts. Each item's page gives the date,
the *In short* takeaways (used as the summary) and the text. Reports and policy briefs only have an abstract
on the page, so the PDF behind the *Read report* button is read as well and its text is added below the abstract.

**Left out.** Podcasts and multimedia. The per-category listings (`/publications?f[0]=type:…`) are not used
because the site's robots.txt asks crawlers to stay off them; the category on the card does the same job.

**Archive.** *Update* looks at the newest pages. *Deep scrape* walks the whole listing, which is several
thousand items and takes a few hours; it can be stopped and continued, items already stored are skipped.
"""
    streams = [Stream("publications", "Publications", LISTING)]
    archive_pages = 1000

    def list_pages(self, stream: Stream, ctx: Context) -> Iterator[ListPage]:
        number = 0
        while True:
            page = self.open(set_query_param(stream.url, "page", number) if number else stream.url, ctx)
            cards = page.soup.select("div.views-row article.node--type-publication")
            if not cards:
                return
            items = []
            for card in cards:
                link = card.select_one("h3.node__title a[href]")
                category = clean(card.select_one(".category").get_text()) if card.select_one(".category") else ""
                if link is None or category not in CATEGORIES:
                    continue
                image = card.select_one(".image-wrapper img[src]")
                items.append(Item(
                    url=canonical_url(page.link(link["href"])),
                    title=clean(link.get_text(" ")),
                    author=", ".join(_names(card.select(".authors a[href*='/person/']"))),
                    image_url=page.link(image["src"]) if image else "",
                    tags=[category],
                ))
            if items:  # a page of podcasts only is not the end of the listing
                yield ListPage(items, page.url, {"cards_on_page": len(cards), "cards_kept": len(items)})
            number += 1

    def read_item(self, item: Item, stream: Stream, ctx: Context) -> Extracted:
        page = self.open(item.url, ctx)
        node = page.soup.select_one("article.node--type-publication.node--view-mode-full")
        body = node.select_one(".node-content .col-md-8") if node else None
        if body is None:
            raise ExtractError(f"{item.url} is not laid out like a Clingendael publication")

        for related in node.select(".node-botom"):  # cards of other publications, with authors of their own
            related.decompose()
        button = node.select_one(".button-wrapper a.button[href]")
        report_url = page.link(button["href"]) if button else ""
        for paragraph in body.find_all("p"):  # the same button, repeated under the text
            link = paragraph.find("a", href=True)
            if link and page.link(link["href"]) == report_url and clean(paragraph.get_text()) == clean(link.get_text()):
                paragraph.decompose()

        takeaways = [clean(point.get_text(" ")) for point in body.select(".summary-wrapper .summary li")]
        if not takeaways:
            summary = body.select_one(".summary-wrapper .summary")
            takeaways = [clean(summary.get_text(" "))] if summary and clean(summary.get_text()) else []
        text = element_text(body)
        pdf_url = report_url if report_url.lower().split("?")[0].endswith(".pdf") else ""
        report = self.pdf_text(pdf_url, ctx) if pdf_url else ""
        text = "\n\n".join(part for part in (text, report) if part)

        dates = (parse_date(element.get_text(" ")) for element in node.select(".top-wrapper .date, .head span"))
        image = page.soup.find("meta", attrs={"property": "og:image"})
        return Extracted(
            author=", ".join(_names(node.select(".authors a[href*='/person/']"))),
            published=next((date for date in dates if date), ""),
            text=text,
            summary=" ".join(takeaways),
            # the card's thumbnail is used when there is one; the page's own image is a megabyte-sized banner
            image_url=page.link(image.get("content")) if image and not item.image_url else "",
            pdf_url=pdf_url,
            language=_language(text),
            content_type=next((CATEGORIES[tag] for tag in item.tags if tag in CATEGORIES), ""),
        )


def _names(links) -> list[str]:
    return list(dict.fromkeys(name for name in (clean(link.get_text(" ")) for link in links) if name))


def _language(text: str) -> str:
    """Clingendael publishes in English and Dutch; the pages themselves all say lang="en"."""
    sample = text[:3000]
    return "nl" if len(DUTCH.findall(sample)) > len(ENGLISH.findall(sample)) else "en"
