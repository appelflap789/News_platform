"""Small text, URL and date helpers shared by the plugins."""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src"}
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption", "figure",
    "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "td", "th", "tr", "ul",
}
SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "iframe"}
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu"}


# --- text ----------------------------------------------------------------------

def clean(text: str | None) -> str:
    """Collapse all whitespace to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def element_text(element: Tag) -> str:
    """Readable text of an element: paragraphs separated by blank lines, inline tags kept in the sentence."""
    parts: list[str] = []
    stack: list = [element]
    while stack:
        node = stack.pop()
        if isinstance(node, str) and not isinstance(node, NavigableString):
            parts.append(node)  # a paragraph break pushed below
        elif isinstance(node, Comment):
            continue
        elif isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag) and node.name not in SKIP_TAGS:
            block = node.name in BLOCK_TAGS
            if block:
                stack.append("\n\n")
            stack.extend(reversed(list(node.children)))
            if block:
                stack.append("\n\n")
    text = "".join(parts).replace("\xa0", " ")
    paragraphs = [clean(p) for p in re.split(r"\n\s*\n", text)]
    return "\n\n".join(p for p in paragraphs if p)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    return element_text(BeautifulSoup(html, "lxml"))


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text or ""))


# --- urls ----------------------------------------------------------------------

def absolutize(base: str, href: str | None) -> str:
    href = (href or "").strip()
    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#", "data:")):
        return ""
    return urljoin(base, href)


def canonical_url(url: str) -> str:
    """Stable form of a URL, used to recognise an article we already have."""
    parts = urlsplit(url.strip())
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def set_query_param(url: str, key: str, value: str | int) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != key]
    query.append((key, str(value)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def registrable_domain(host: str) -> str:
    """'www.clingendael.org' -> 'clingendael.org'; 'news.bbc.co.uk' -> 'bbc.co.uk' (good-enough heuristic)."""
    labels = host.lower().strip(".").split(".")
    if len(labels) <= 2:
        return ".".join(labels)
    if len(labels[-1]) == 2 and labels[-2] in SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def same_site(url_a: str, url_b: str) -> bool:
    return registrable_domain(host_of(url_a)) == registrable_domain(host_of(url_b))


# --- dates ---------------------------------------------------------------------

YEAR_ONLY = "-01-01T00:00:00Z"


def better_date(listed: str, from_page: str) -> str:
    """The listing's date normally wins (it is what the site shows), unless it is only a year."""
    if listed.endswith(YEAR_ONLY) and from_page:
        return from_page
    return listed or from_page


def parse_date(value) -> str:
    """Anything date-like -> 'YYYY-MM-DDTHH:MM:SSZ' in UTC, or '' when it cannot be read."""
    if not value:
        return ""
    parsed: datetime | None = None
    if isinstance(value, time.struct_time):
        parsed = datetime(*value[:6], tzinfo=timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = clean(str(value))
        if not text or len(text) > 80 or not re.search(r"\d", text):
            return ""
        if re.fullmatch(r"(19|20)\d\d", text):
            return f"{text}{YEAR_ONLY}"  # a bare year: keep it for sorting, marked as coarse
        parsed = _parse_date_text(text)
    if parsed is None:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc)
    if not 1990 <= parsed.year <= datetime.now(timezone.utc).year + 1:
        return ""
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_date_text(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    import dateparser  # slow import, only needed for free-form dates such as "12 maart 2024"

    try:
        return dateparser.parse(text, settings={"DATE_ORDER": "DMY", "PREFER_DAY_OF_MONTH": "first"})
    except Exception:
        return None
