"""Pagination shared by the connectors that walk numbered or linked pages."""

from __future__ import annotations

from bs4 import BeautifulSoup

from ..dom import select_one
from ..registry import Field
from ..schemas import FeedRecipe
from ..util import absolutize, set_query_param
from .base import ConnectorError

PAGINATION_FIELDS = [
    Field(
        "pagination", "Pagination", type="select",
        choices=("none", "next_link", "page_param", "url_template"),
        help="How to reach older items. none = single page. next_link = follow a 'next' link. "
             "page_param = a page number in the query string. url_template = a page number inside the URL.",
    ),
    Field("next_selector", "Next-link selector",
          help="For next_link on HTML pages: CSS selector of the <a> that leads to the next page."),
    Field("page_param", "Page parameter", help="For page_param: the query parameter name, e.g. 'page' or 'paged'."),
    Field("page_template", "Page URL template",
          help="For url_template: full URL with {page} where the number goes, e.g. https://site.org/news/page/{page}/"),
    Field("page_start", "First page number", type="number",
          help="The number that the start URL itself represents (often 1, on Drupal sites 0). Default 1."),
    Field("page_step", "Page step", type="number",
          help="How much the number grows per page (1 for page numbers, e.g. 20 for offsets). Default 1."),
]


def next_page_url(feed: FeedRecipe, current_url: str, page_index: int, soup: BeautifulSoup | None = None,
                  atom_next: str = "") -> str:
    """URL of the page after `page_index` (0 = the feed's start URL), or '' when there is none."""
    mode = feed.opt("pagination", "none")
    if mode == "none":
        return ""
    if mode == "next_link":
        if atom_next:
            return absolutize(current_url, atom_next)
        selector = feed.opt("next_selector")
        if soup is None or not selector:
            return ""
        link = select_one(soup, selector, "next_selector")
        return absolutize(current_url, link.get("href")) if link else ""
    number = feed.opt_int("page_start", 1) + feed.opt_int("page_step", 1) * (page_index + 1)
    if mode == "page_param":
        param = feed.opt("page_param")
        if not param:
            raise ConnectorError("pagination is page_param but page_param is not set")
        return set_query_param(feed.url, param, number)
    if mode == "url_template":
        template = feed.opt("page_template")
        if "{page}" not in template:
            raise ConnectorError("pagination is url_template but page_template has no {page} placeholder")
        return template.replace("{page}", str(number))
    raise ConnectorError(f"Unknown pagination mode '{mode}'")
