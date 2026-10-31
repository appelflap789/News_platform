"""The cheap first look at a new source: what kind of thing is this URL, and which feeds and sitemaps exist?

Both analyzers start here. The heuristic analyzer turns the result straight into
a recipe; the Claude analyzer hands it to Claude so it does not spend tool calls
rediscovering it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from ..connectors import Context
from ..connectors.rss import parse_feed
from ..errors import ScrapeError
from ..fetchers import FetchError, FetchResult, fetchers
from ..jobs import Job
from ..util import clean, host_of, parse_date, registrable_domain
from ._digest import page_info

COMMON_FEED_PATHS = ["/rss.xml", "/feed", "/feed.xml", "/rss", "/atom.xml", "/index.xml"]
MAX_FEEDS_TO_CHECK = 6


@dataclass
class Prescan:
    url: str
    kind: str = "html"  # html | feed | sitemap | pdf | reddit | youtube | podcast
    final_url: str = ""
    site_name: str = ""
    description: str = ""
    language: str = ""
    icon_url: str = ""
    feeds: list[dict] = field(default_factory=list)  # {"url", "title", "entries", "latest", "full_content"}
    sitemaps: list[str] = field(default_factory=list)
    start: FetchResult | None = None
    blocked: str = ""  # why the start page could not be opened, when it could not

    @property
    def homepage(self) -> str:
        parts = urlsplit(self.final_url or self.url)
        return f"{parts.scheme}://{parts.netloc}/"

    def summary(self) -> str:
        lines = [f"Kind of URL: {self.kind}"]
        if self.blocked:
            lines.append(f"The start page could not be opened: {self.blocked}")
        if self.feeds:
            lines.append("Working feeds found:")
            lines.extend(
                f"- {f['url']} - \"{f['title']}\", {f['entries']} entries, newest {f['latest'][:10] or 'unknown'}, "
                f"{'full text in feed' if f['full_content'] else 'summaries only'}"
                for f in self.feeds
            )
        else:
            lines.append("Working feeds found: none")
        lines.append("Sitemaps: " + (", ".join(self.sitemaps[:6]) if self.sitemaps else "none found"))
        return "\n".join(lines)


def is_reddit(url: str) -> bool:
    return registrable_domain(host_of(url)) in ("reddit.com", "redd.it")


def check_feed(url: str, ctx: Context) -> dict | None:
    """Details of a feed URL, or None when it is not a working feed."""
    try:
        result = ctx.fetch(url, robots=False)
        parsed = parse_feed(result.content, url)
    except ScrapeError:
        return None
    if not parsed.entries:
        return None
    dates = sorted(d for d in (parse_date(e.get("published_parsed") or e.get("updated_parsed"))
                               for e in parsed.entries) if d)
    return {
        "url": result.url,
        "title": clean(parsed.feed.get("title", "")),
        "entries": len(parsed.entries),
        "latest": dates[-1] if dates else "",
        "full_content": sum(1 for e in parsed.entries if e.get("content")) > len(parsed.entries) / 2,
    }


def is_youtube(url: str) -> bool:
    from ..connectors.youtube import is_youtube as check

    return check(url)


def is_spotify(url: str) -> bool:
    from ..connectors.podcast import is_spotify as check

    return check(url)


def prescan(url: str, ctx: Context, job: Job | None = None) -> Prescan:
    scan = Prescan(url=url)
    if is_reddit(url):
        scan.kind = "reddit"
        scan.final_url = url
        scan.site_name = "Reddit"
        return scan
    if is_youtube(url):
        scan.kind = "youtube"
        scan.final_url = url
        scan.site_name = "YouTube"
        return scan
    if is_spotify(url):
        scan.kind = "podcast"
        scan.final_url = url
        scan.site_name = "Spotify"
        return scan

    try:
        result = ctx.fetch(url)
    except FetchError as error:
        if not error.refused:
            raise  # a page that does not exist is a typo to report, not a site to work around
        return _prescan_blocked(scan, ctx, error)
    scan.start = result
    scan.final_url = result.url
    scan.site_name = registrable_domain(host_of(result.url))

    if result.is_pdf:
        scan.kind = "pdf"
        return scan
    if result.is_xml:
        head = result.content[:3000].lower()
        if b"<urlset" in head or b"<sitemapindex" in head:
            scan.kind = "sitemap"
            scan.sitemaps = [result.url]
            return scan
        found = check_feed(result.url, ctx)
        if found:
            scan.kind = "feed"
            scan.feeds = [found]
            scan.site_name = _name_from_feed(found["title"]) or scan.site_name
            return scan

    soup = BeautifulSoup(result.text, "lxml")
    info = page_info(soup, result.url)
    scan.site_name = info.site_name or _name_from_title(info.title) or scan.site_name
    scan.description = info.description
    scan.language = info.language[:2].lower()
    scan.icon_url = info.icon_url or scan.homepage + "favicon.ico"

    candidates = [f["url"] for f in info.feeds if "comment" not in f["url"].lower()]
    if not candidates:
        candidates = [scan.homepage.rstrip("/") + path for path in COMMON_FEED_PATHS]
    seen: set[str] = set()
    for candidate in candidates[:MAX_FEEDS_TO_CHECK]:
        if job:
            job.check_cancelled()
        found = check_feed(candidate, ctx)
        if found and found["url"] not in seen:
            seen.add(found["url"])
            scan.feeds.append(found)
            if not info.feeds:
                break  # one guessed feed is enough; the common paths are usually aliases of each other

    scan.sitemaps = _sitemaps(scan, ctx)
    return scan


def _prescan_blocked(scan: Prescan, ctx: Context, error: FetchError) -> Prescan:
    """The start page is refused (bot protection, robots.txt). Sites often still serve their feed, so look for one."""
    scan.final_url = scan.url
    scan.blocked = str(error)
    scan.site_name = registrable_domain(host_of(scan.url))
    scan.icon_url = scan.homepage + "favicon.ico"
    parts = urlsplit(scan.url)
    host = parts.netloc
    twin = host[4:] if host.startswith("www.") else f"www.{host}"
    for origin in (f"{parts.scheme}://{host}", f"{parts.scheme}://{twin}"):
        for path in COMMON_FEED_PATHS:
            found = check_feed(origin + path, ctx)
            if found:
                scan.feeds.append(found)
                scan.site_name = _name_from_feed(found["title"]) or scan.site_name
                scan.final_url = origin + "/"
                return scan
    raise error


def _sitemaps(scan: Prescan, ctx: Context) -> list[str]:
    fetcher = fetchers.get("http")
    advertised = fetcher.sitemaps_from_robots(scan.final_url) if hasattr(fetcher, "sitemaps_from_robots") else []
    if advertised:
        return advertised
    guess = scan.homepage + "sitemap.xml"
    try:
        result = ctx.fetch(guess)
    except ScrapeError:
        return []
    head = result.content[:3000].lower()
    return [result.url] if (b"<urlset" in head or b"<sitemapindex" in head) else []


def _name_from_feed(title: str) -> str:
    """'Clingendael - International Affairs Think Tank' -> 'Clingendael'"""
    for separator in (" | ", " - ", " – ", " — ", " · ", ": "):
        if separator in title:
            return clean(title.split(separator)[0])
    return clean(title)


def _name_from_title(title: str) -> str:
    """'Publications | Clingendael' -> 'Clingendael'"""
    for separator in (" | ", " - ", " – ", " — ", " · "):
        if separator in title:
            return clean(title.split(separator)[-1])
    return clean(title)
