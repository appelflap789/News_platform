from __future__ import annotations

from dataclasses import dataclass

from ..errors import ScrapeError
from ..registry import Registry


class FetchError(ScrapeError):
    """A download failed in a way worth showing to the user (blocked, 404, too large, ...).

    `refused` is True when the site (or its robots.txt) turned the request away, as opposed to the page
    not existing: in that case other doors, such as the site's feed, may still be open. `status` is the
    HTTP status the server answered with, or 0 when it never came to an answer (a timeout, robots.txt).
    """

    def __init__(self, message: str, *, refused: bool = False, status: int = 0):
        super().__init__(message)
        self.refused = refused
        self.status = status


@dataclass
class FetchResult:
    url: str  # final URL after redirects
    status: int
    content_type: str
    content: bytes
    encoding: str = ""

    @property
    def text(self) -> str:
        for encoding in (self.encoding, "utf-8"):
            if not encoding:
                continue
            try:
                return self.content.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return self.content.decode("utf-8", errors="replace")

    @property
    def is_pdf(self) -> bool:
        return "pdf" in self.content_type or self.content[:5] == b"%PDF-"

    @property
    def is_html(self) -> bool:
        if "html" in self.content_type:
            return True
        head = self.content[:600].lstrip().lower()
        return head.startswith((b"<!doctype html", b"<html"))

    @property
    def is_xml(self) -> bool:
        if self.is_html:
            return False
        if "xml" in self.content_type or "rss" in self.content_type or "atom" in self.content_type:
            return True
        return self.content[:200].lstrip().startswith((b"<?xml", b"<rss", b"<feed", b"<urlset", b"<sitemapindex"))

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type


class Fetcher:
    name = ""
    label = ""
    description = ""

    def fetch(self, url: str, *, max_bytes: int | None = None, robots: bool = True) -> FetchResult:
        """Download `url`. `robots=False` is for documents the user subscribed to (feeds): robots.txt is
        written for crawlers that discover pages, not for a reader fetching the feed it was pointed at."""
        raise NotImplementedError


fetchers: Registry[Fetcher] = Registry("fetcher")
