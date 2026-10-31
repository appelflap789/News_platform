"""CSS-selector helpers shared by connectors and extractors."""

from __future__ import annotations

from bs4 import Tag

from .errors import ScrapeError
from .util import absolutize, parse_date


class SelectorError(ScrapeError):
    """A CSS selector in a recipe is not valid."""


def select(root, selector: str, what: str) -> list[Tag]:
    try:
        return root.select(selector)
    except Exception as error:  # soupsieve raises its own SelectorSyntaxError
        raise SelectorError(f"{what} '{selector}' is not a valid CSS selector: {error}") from error


def select_one(root, selector: str, what: str) -> Tag | None:
    found = select(root, selector, what)
    return found[0] if found else None


def image_src(image: Tag | None, base_url: str) -> str:
    """The URL of an image element, coping with lazy-loading attributes."""
    if image is None:
        return ""
    if image.name != "img":
        image = image.find("img") or image
    for attribute in ("src", "data-src", "data-lazy-src", "data-original"):
        value = image.get(attribute, "")
        if value and not value.startswith("data:"):
            return absolutize(base_url, value)
    srcset = image.get("srcset") or image.get("data-srcset") or ""
    if srcset:
        return absolutize(base_url, srcset.split(",")[0].strip().split(" ")[0])
    return ""


def date_of(element: Tag | None) -> str:
    """The date an element states, preferring machine-readable attributes over its text."""
    if element is None:
        return ""
    return parse_date(element.get("datetime") or element.get("content") or element.get_text(" "))
