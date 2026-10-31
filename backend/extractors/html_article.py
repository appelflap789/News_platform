"""Web pages: automatic main-text detection, with optional CSS selectors from the recipe on top."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..dom import date_of, image_src, select_one
from ..fetchers import FetchError, FetchResult
from ..registry import Field
from ..util import absolutize, clean, element_text, parse_date
from . import _walls
from .base import Extracted, ExtractError, Extractor, extractors

MIN_TEXT = 200


def _meta(soup: BeautifulSoup, *names: str) -> str:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            return clean(tag["content"])
    return ""


def _tags(found) -> list[str]:
    """A page's keywords as a clean list. Sites write them as separate tags, as one comma-separated line, or both."""
    if not isinstance(found, list):
        return []
    parts = (clean(part) for entry in found for part in re.split(r"[,;]", str(entry)))
    return list(dict.fromkeys(part for part in parts if part))


def _automatic(html: str, url: str) -> dict:
    """Main text and metadata as found by trafilatura."""
    import trafilatura

    def run(**mode) -> dict:
        try:
            document = trafilatura.bare_extraction(
                html, url=url, with_metadata=True, include_comments=False, include_tables=True, **mode
            )
        except Exception:
            return {}
        if document is None:
            return {}
        return document.as_dict() if hasattr(document, "as_dict") else dict(document)

    found = run()
    if len(found.get("text") or "") < MIN_TEXT:
        # The balanced mode leaves out bylines and sign-up boxes, but on sparse pages it can miss the text itself.
        greedy = run(favor_recall=True)
        if len(greedy.get("text") or "") > len(found.get("text") or ""):
            return greedy
    return found


@extractors.register
class HtmlArticleExtractor(Extractor):
    name = "html"
    label = "Web page"
    description = "Finds the main text of a web page automatically; selectors in the recipe override what it finds."
    priority = 50
    fields = [
        Field("body_selector", "Body selector",
              help="CSS selector of the element holding the full text. Empty = automatic detection (usually fine)."),
        Field("title_selector", "Title selector", help="Empty = automatic."),
        Field("date_selector", "Date selector", help="Empty = automatic (meta tags, <time>)."),
        Field("author_selector", "Author selector", help="Empty = automatic."),
        Field("image_selector", "Image selector", help="Empty = the page's social-share image."),
        Field("pdf_link_selector", "PDF link selector",
              help="CSS selector of the <a> to the full report as PDF, when item pages offer one. "
                   "Empty = the first PDF link inside the main content, if any."),
        Field("extract_pdf_text", "Read linked PDF", type="select", choices=("false", "true"),
              help="true = also download that PDF and use its text when it is longer than the page text "
                   "(for sites where the page is only an abstract)."),
    ]

    def matches(self, result: FetchResult) -> bool:
        return result.is_html

    def extract(self, result: FetchResult, rules: dict[str, str], ctx) -> Extracted:
        html = result.text
        soup = BeautifulSoup(html, "lxml")
        auto = _automatic(html, result.url)

        def pick(key: str):
            selector = rules.get(key, "")
            return select_one(soup, selector, key) if selector else None

        body = pick("body_selector")
        text = element_text(body) if body is not None else clean_paragraphs(auto.get("text") or "")
        if len(text) < MIN_TEXT:
            container = soup.find("article") or soup.find("main") or soup.body
            fallback = element_text(container) if container else ""
            text = fallback if len(fallback) > len(text) else text

        title_node, author_node, image_node = pick("title_selector"), pick("author_selector"), pick("image_selector")
        date_node = pick("date_selector")
        extracted = Extracted(
            title=clean(title_node.get_text(" ")) if title_node else (
                clean(auto.get("title")) or _meta(soup, "og:title") or clean(soup.title.get_text() if soup.title else "")
            ),
            author=clean(author_node.get_text(" ")) if author_node else clean(auto.get("author")),
            published=date_of(date_node) if date_node else (
                parse_date(_meta(soup, "article:published_time", "date", "dc.date", "dcterms.date"))
                or parse_date(auto.get("date"))
            ),
            text=text,
            summary=clean(auto.get("description")) or _meta(soup, "og:description", "description"),
            image_url=image_src(image_node, result.url) if image_node else absolutize(
                result.url, _meta(soup, "og:image", "twitter:image") or (auto.get("image") or "")
            ),
            language=(auto.get("language") or (soup.html.get("lang", "") if soup.html else "") or "")[:2].lower(),
            tags=_tags(auto.get("tags")),
        )
        extracted.pdf_url = self._pdf_link(soup, body, rules, result.url)
        if extracted.pdf_url and rules.get("extract_pdf_text") == "true":
            self._merge_pdf(extracted, ctx)
        extracted.wall = _walls.on_page(result.url, soup, extracted.text)
        if len(extracted.text) < MIN_TEXT and not extracted.pdf_url:
            if extracted.wall:
                raise ExtractError(f"{result.url} cannot be read: {extracted.wall}")
            raise ExtractError(
                f"Almost no text found on {result.url} - the page may need JavaScript, a login, or a body_selector"
            )
        return extracted

    @staticmethod
    def _pdf_link(soup: BeautifulSoup, body, rules: dict[str, str], base_url: str) -> str:
        selector = rules.get("pdf_link_selector", "")
        if selector:
            link = select_one(soup, selector, "pdf_link_selector")
            return absolutize(base_url, link.get("href")) if link else ""
        for scope in (body, soup.find("article"), soup.find("main")):
            if scope is None:
                continue
            for link in scope.find_all("a", href=True):
                if link["href"].lower().split("?")[0].endswith(".pdf"):
                    return absolutize(base_url, link["href"])
        return ""

    @staticmethod
    def _merge_pdf(extracted: Extracted, ctx) -> None:
        """Replace the abstract with the report itself when the PDF is the real content."""
        from .pdf_document import pdf_text

        try:
            download = ctx.fetch(extracted.pdf_url)
            if not download.is_pdf:
                return
            text, metadata = pdf_text(download.content, extracted.pdf_url)
        except (FetchError, ExtractError):
            return  # the page text is still worth keeping
        if len(text) > len(extracted.text):
            if not extracted.summary:
                extracted.summary = extracted.text[:600]
            extracted.text = text
            extracted.content_type = "report"
        extracted.author = extracted.author or metadata["author"]
        extracted.published = extracted.published or metadata["published"]


def clean_paragraphs(text: str) -> str:
    return "\n\n".join(p for p in (clean(line) for line in text.split("\n")) if p)
