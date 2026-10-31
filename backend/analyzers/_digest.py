"""Shrink a downloaded page into something Claude can read cheaply without losing its structure.

A news homepage is easily 500 KB of HTML, most of it scripts, styling and the
same card repeated thirty times. The digest keeps the skeleton: scripts and
styling are dropped, attributes are reduced to the ones selectors are written
against, long texts are shortened, and runs of look-alike siblings are collapsed
to the first three. What was cut is always stated, so Claude can zoom in with a
selector instead of guessing.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Comment, Tag

from ..connectors.rss import parse_feed
from ..dom import select
from ..errors import ScrapeError
from ..fetchers import FetchResult
from ..util import absolutize, clean, parse_date, same_site, truncate

DROP_TAGS = ["script", "style", "noscript", "svg", "iframe", "template", "link", "meta", "canvas", "video", "audio"]
KEEP_ATTRS = {"id", "class", "href", "src", "data-src", "datetime", "rel", "role", "aria-label", "itemprop",
              "itemtype", "type", "name", "lang"}
FEED_TYPES = ("rss", "atom")
KEEP_SIBLINGS = 3
TEXT_LIMIT = 160
BLOCK_BREAK = re.compile(r"(<(?:div|article|section|li|ul|ol|nav|header|footer|main|h[1-6]|p|table|tr|form|aside)\b)")


@dataclass
class PageInfo:
    title: str = ""
    site_name: str = ""
    description: str = ""
    language: str = ""
    icon_url: str = ""
    feeds: list[dict] = field(default_factory=list)  # {"url", "title"}
    schema_types: list[str] = field(default_factory=list)


def page_info(soup: BeautifulSoup, base_url: str) -> PageInfo:
    def meta(*names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return clean(tag["content"])
        return ""

    info = PageInfo(
        title=clean(soup.title.get_text()) if soup.title else "",
        site_name=meta("og:site_name", "application-name"),
        description=meta("description", "og:description"),
        language=(soup.html.get("lang", "") if soup.html else "")[:5],
    )
    icons = {}
    for link in soup.find_all("link", href=True):
        rel = " ".join(link.get("rel") or []).lower()
        kind = (link.get("type") or "").lower()
        if "alternate" in rel and any(t in kind for t in FEED_TYPES):
            info.feeds.append({"url": absolutize(base_url, link["href"]), "title": clean(link.get("title") or "")})
        elif "icon" in rel:
            icons["apple" if "apple" in rel else "icon"] = absolutize(base_url, link["href"])
    info.icon_url = icons.get("apple") or icons.get("icon") or ""
    types: list[str] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            types.extend(_schema_types(json.loads(script.string or "")))
        except (ValueError, TypeError):
            continue
    info.schema_types = list(dict.fromkeys(types))[:12]
    return info


def _schema_types(node) -> list[str]:
    if isinstance(node, list):
        return [t for item in node for t in _schema_types(item)]
    if not isinstance(node, dict):
        return []
    own = node.get("@type", [])
    found = [own] if isinstance(own, str) else [t for t in own if isinstance(t, str)]
    return found + _schema_types(node.get("@graph", []))


def describe(result: FetchResult, selector: str = "", max_chars: int = 40_000) -> str:
    """The digest of any download, as text for Claude."""
    head = (f"URL: {result.url}\nHTTP {result.status} · {result.content_type or 'unknown content type'}"
            f" · {len(result.content):,} bytes\n")
    if result.is_pdf:
        return head + _pdf(result)
    if result.is_html:
        return head + _html(result, selector, max_chars)
    if result.is_xml:
        return head + _xml(result)
    return head + "\n" + _cut(result.text, 6_000)


# --- HTML -------------------------------------------------------------------------

def _html(result: FetchResult, selector: str, max_chars: int) -> str:
    soup = BeautifulSoup(result.text, "lxml")
    info = page_info(soup, result.url)
    lines = [f"Title: {info.title}"]
    if info.site_name:
        lines.append(f"Site name: {info.site_name}")
    if info.language:
        lines.append(f"Language: {info.language}")
    if info.description:
        lines.append(f"Description: {truncate(info.description, 300)}")
    if info.feeds:
        lines.append("Feeds advertised: " + "; ".join(f"{f['url']} ({f['title'] or 'untitled'})" for f in info.feeds[:8]))
    if info.schema_types:
        lines.append("schema.org types in JSON-LD: " + ", ".join(info.schema_types))

    body = soup.body or soup
    for tag in body.find_all(DROP_TAGS):
        tag.decompose()
    for comment in body.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    visible = len(clean(body.get_text(" ")))
    if visible < 300:
        lines.append(
            f"WARNING: only {visible} characters of text are in this HTML. The page is probably rendered with "
            "JavaScript, which the scraper cannot run."
        )

    if selector:
        matches = select(soup, selector, "selector")
        if not matches:
            return "\n".join(lines) + f"\n\nNo element matches the selector {selector!r} on this page."
        lines.append(f"{len(matches)} element(s) match {selector!r}; showing the first {min(len(matches), 5)} in full.")
        roots = matches[:5]
    else:
        lines.extend(_link_overview(body, result.url))
        roots = [body]

    for root in roots:
        _simplify(root)
        if not selector:
            _collapse(root)
    html = "\n".join(_compact(root) for root in roots)
    note = ""
    if len(html) > max_chars:
        note = (f"\n[Outline cut at {max_chars:,} of {len(html):,} characters. Call fetch_page again with a "
                "`selector` to see one region in full.]")
        html = html[:max_chars]
    kind = "Matched elements" if selector else f"Page outline (runs of similar siblings show the first {KEEP_SIBLINGS})"
    return "\n".join(lines) + f"\n\n{kind}:\n{html}{note}"


def _link_overview(body: Tag, base_url: str) -> list[str]:
    """Navigation links and the most common link paths: the quickest way to see a site's sections."""
    lines: list[str] = []
    navigation: dict[str, str] = {}
    for area in body.find_all(["nav", "header"]):
        for link in area.find_all("a", href=True):
            url, text = absolutize(base_url, link["href"]), clean(link.get_text(" "))
            if url and text and same_site(url, base_url):
                navigation.setdefault(url, text)
    if navigation:
        shown = list(navigation.items())[:50]
        lines.append("Navigation links: " + " | ".join(f"{truncate(text, 40)} -> {urlsplit(url).path or '/'}"
                                                         for url, text in shown))
    patterns: Counter[str] = Counter()
    for link in body.find_all("a", href=True):
        url = absolutize(base_url, link["href"])
        if not url or not same_site(url, base_url):
            continue
        segments = [s for s in urlsplit(url).path.split("/") if s]
        if segments:
            patterns["/" + segments[0] + ("/…" if len(segments) > 1 else "")] += 1
    if patterns:
        lines.append("Most common link paths: " + ", ".join(f"{p} ×{n}" for p, n in patterns.most_common(15)))
    return lines


def _simplify(root: Tag) -> None:
    for tag in [root, *root.find_all(True)]:
        kept = {}
        for key, value in tag.attrs.items():
            if key not in KEEP_ATTRS:
                continue
            if key == "class":
                value = value[:5] if isinstance(value, list) else value
            elif isinstance(value, str):
                if value.startswith("data:"):
                    continue
                value = truncate(value, 160)
            kept[key] = value
        tag.attrs = kept
    for text in root.find_all(string=True):
        if len(text) > TEXT_LIMIT:
            text.replace_with(text[: TEXT_LIMIT - 1] + "…")


def _signature(tag: Tag) -> str:
    classes = tag.get("class") or []
    return tag.name + ("." + classes[0] if classes else "")


def _collapse(node: Tag, depth: int = 0) -> None:
    """Replace long runs of look-alike siblings by their first few plus a note saying how many were dropped."""
    if depth > 150:
        return
    children = [child for child in node.children if isinstance(child, Tag)]
    runs: list[list[Tag]] = []
    for child in children:
        if runs and _signature(runs[-1][0]) == _signature(child):
            runs[-1].append(child)
        else:
            runs.append([child])
    for run in runs:
        if len(run) > KEEP_SIBLINGS:
            extra = run[KEEP_SIBLINGS:]
            extra[0].insert_before(Comment(f" +{len(extra)} more {_signature(run[0])} elements like the ones above "))
            for tag in extra:
                tag.decompose()
        for tag in run[:KEEP_SIBLINGS]:
            _collapse(tag, depth + 1)


def _compact(root: Tag) -> str:
    html = re.sub(r"\s+", " ", root.decode())
    html = html.replace("> <", "><")
    return BLOCK_BREAK.sub(r"\n\1", html).strip()


# --- feeds, sitemaps, PDFs -----------------------------------------------------------

def _xml(result: FetchResult) -> str:
    start = result.content[:3000].lower()
    if b"<urlset" in start or b"<sitemapindex" in start:
        return _sitemap(result)
    try:
        parsed = parse_feed(result.content, result.url)
    except ScrapeError:
        return "\nXML, but neither a feed nor a sitemap. Start of the document:\n" + _cut(result.text, 4_000)
    entries = parsed.entries
    lines = [f"\nRSS/Atom feed \"{clean(parsed.feed.get('title', ''))}\" with {len(entries)} entries."]
    if entries:
        full = [len(e.content[0].get("value", "")) for e in entries if e.get("content")]
        summaries = [len(e.get("summary", "")) for e in entries]
        dates = sorted(d for d in (parse_date(e.get("published_parsed") or e.get("updated_parsed")) for e in entries) if d)
        lines.append(f"Entries with a full-content field: {len(full)}"
                     + (f" (average {sum(full) // len(full):,} characters of HTML)" if full else ""))
        lines.append(f"Average summary length: {sum(summaries) // len(summaries):,} characters")
        if dates:
            lines.append(f"Entry dates range from {dates[0][:10]} to {dates[-1][:10]}")
        next_link = next((l.get("href") for l in parsed.feed.get("links", []) if l.get("rel") == "next"), "")
        if next_link:
            lines.append(f"The feed links to a next page: {next_link}")
        lines.append("First entries:")
        for entry in entries[:6]:
            date = parse_date(entry.get("published_parsed") or entry.get("updated_parsed"))[:10]
            lines.append(f"- {date or 'no date'} | {truncate(clean(entry.get('title', '')), 110)} | {entry.get('link', '')}")
    return "\n".join(lines)


def _sitemap(result: FetchResult) -> str:
    soup = BeautifulSoup(result.content, "xml")
    children = [clean(s.loc.get_text()) for s in soup.find_all("sitemap") if s.loc]
    if children:
        return (f"\nSitemap index with {len(children)} child sitemaps:\n"
                + "\n".join(f"- {u}" for u in children[:40]))
    urls = [clean(u.loc.get_text()) for u in soup.find_all("url") if u.loc]
    patterns: Counter[str] = Counter()
    for url in urls:
        segments = [s for s in urlsplit(url).path.split("/") if s]
        patterns["/" + "/".join(segments[:1]) + ("/…" if len(segments) > 1 else "")] += 1
    return (f"\nSitemap with {len(urls):,} URLs.\nURL paths: "
            + ", ".join(f"{p} ×{n}" for p, n in patterns.most_common(20))
            + "\nSample URLs:\n" + "\n".join(f"- {u}" for u in urls[:25]))


def _pdf(result: FetchResult) -> str:
    from ..extractors.pdf_document import pdf_text

    try:
        text, metadata = pdf_text(result.content, result.url)
    except ScrapeError as error:
        return f"\nPDF document that could not be read: {error}"
    return (f"\nPDF document, {metadata['pages']} pages. Title in metadata: {metadata['title'] or '(none)'}.\n"
            f"Start of the text:\n{truncate(text, 1_200)}")


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[Cut at {limit:,} of {len(text):,} characters.]"
