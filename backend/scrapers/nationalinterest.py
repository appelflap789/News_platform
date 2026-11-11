"""The National Interest, the American foreign-policy magazine (nationalinterest.org).

The site is WordPress with two kinds of content: blog posts (`/blog/<blog>/<slug>`: The Buzz, Techland, Energy
World, Korea Watch, Middle East Watch, Silk Road Rivalries, US Politics and some older columnists) and features
(`/feature/<slug>`). The menus' Regions, Military, Politics and Technology are not sections of their own: they
are filters (`/region/…`, `/topics/…`, `/tags/…`) over those same posts and features.

The site's REST API answers 401, so the doors are its RSS feeds: `/feed` (every blog post) and `/feature/feed`
(every feature), ten items a page, `?paged=N` back to 2012, HTTP 404 past the end; and a feed per topic
(`/topics/<slug>/feed`), which mixes both kinds. A feed item has the title, author, date, the site's tags and
the full text, but not the region, blog or topic. Those are only on the item's own page, in a block under the
text (`.article-taxonomy`: "Region:", "Blog:", "Topic:", "Tags:"), so every item's page is opened and they
become its tags. An item with a topic from the site's Technology menu, or from the Techland blog, also gets
the tag "Technology".

Pages: the title, the date and the authors are in the header (`.header__title`, `article:published_time`,
`.header__meta--taxonomy` links to `/profile/…`), the text is the rest of `main.main`. Newer pieces start with
a one-sentence standfirst (`main > h2`), which is the summary. Blocks of ads (`.tni-poster`) and of related
posts sit between the paragraphs.

robots.txt allows everything to `*` and asks for ten seconds between requests (`Crawl-delay: 10`). The
platform's fetcher does not read that line, so this scraper keeps to it itself.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import feedparser

from ..fetchers import FetchError, FetchResult
from ..util import canonical_url, clean, element_text, html_to_text, parse_date, set_query_param
from .base import Context, Extracted, ExtractError, Item, ListPage, SiteScraper, Stream, scrapers

HOME = "https://nationalinterest.org"
BLOGS = f"{HOME}/feed"
FEATURES = f"{HOME}/feature/feed"
# The Technology menu of the site, topic -> its slug. The Techland blog counts as technology too.
TECHNOLOGY = {
    "Artificial Intelligence (AI)": "ai-artificial-intelligence",
    "Cryptocurrency": "cryptocurrency",
    "Cybersecurity": "cybersecurity",
    "Digital Infrastructure": "digital-infrastructure",
    "Robotics": "robotics",
    "Space": "space",
}
TECH_FEEDS = [f"{HOME}/topics/{slug}/feed" for slug in TECHNOLOGY.values()]
TECH_BLOG = "Techland"
PER_PAGE = 10  # items handed to the platform at a time, as many as a feed page has
PACE = 10.0  # seconds between requests to the site: its robots.txt asks for this
CUT = (".header", ".tni-poster", ".related-posts", ".article-taxonomy", ".share", "script", "style", "noscript",
       "iframe", "form", "figure.wp-block-embed")

_last_request = 0.0
_pace_lock = threading.Lock()


@scrapers.register
class NationalInterest(SiteScraper):
    name = "nationalinterest"
    label = "The National Interest"
    homepage = HOME
    description = ("The National Interest, the American foreign-policy magazine: features and the blogs The Buzz, "
                   "Techland, Energy World, Korea Watch, Middle East Watch, Silk Road Rivalries and US Politics.")
    language = "en"
    icon_url = f"{HOME}/wp-content/uploads/2024/11/cropped-favicon-300x300.png"
    notes = """\
Built scraper (`backend/scrapers/nationalinterest.py`).

**Two feeds.** *All articles* is everything the site publishes: its blog posts (`/feed`) and its features
(`/feature/feed`), merged newest first. *Technology* reads the site's six Technology topics (Artificial
Intelligence, Cryptocurrency, Cybersecurity, Digital Infrastructure, Robotics, Space) merged newest first; on
an update it adds nothing *All articles* does not already have, but a deep scrape of it goes back through the
technology archive alone instead of through all of it.

**Regions, topics, blogs.** The site's menus (Regions, Military, Politics, Technology) are filters over the same
articles, not separate sections, so nothing is missed by reading the two main feeds. Each item's own page names
its region, blog, topics and tags; they become the item's tags, and an item on a technology topic or on the
Techland blog also gets the tag *Technology*. A topic with the words "Technology" and "Artificial Intelligence"
finds them.

**Collected per item.** Title, authors, date, the standfirst as summary, the full text, the picture and the tags.
If an item's page cannot be read, the text from the feed is kept.

**Pace.** The site's robots.txt asks for ten seconds between requests, and this scraper keeps to that: about
six items a minute. The site publishes about ten items a day.

**How much.** The first scrape takes the newest 30 of each feed (about five minutes). *Update* looks at the
newest pages. The full archive goes back to 2012 and is about 100,000 items, which at this pace is more than a
week: use *Deep scrape* with a number ("go back until it has N items"), not *everything*.
"""
    streams = [
        Stream("all", "All articles", BLOGS),
        Stream("technology", "Technology", TECH_FEEDS[0]),
    ]
    archive_pages = 11000  # about 100,000 items, ten a page

    # -- downloads -------------------------------------------------------------------------------

    def fetch(self, url: str, ctx: Context) -> FetchResult:
        global _last_request
        with _pace_lock:  # one request at a time, ten seconds apart, also when two feeds run at once
            wait = _last_request + PACE - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                return super().fetch(url, ctx)
            finally:
                _last_request = time.monotonic()

    # -- listing ---------------------------------------------------------------------------------

    def list_pages(self, stream: Stream, ctx: Context) -> Iterator[ListPage]:
        feeds = TECH_FEEDS if stream.key == "technology" else [BLOGS, FEATURES]
        page: list[Item] = []
        for item in self._merged(feeds, ctx):
            page.append(item)
            if len(page) == PER_PAGE:
                yield ListPage(page, stream.url, {"feeds": len(feeds)})
                page = []
        if page:
            yield ListPage(page, stream.url, {"feeds": len(feeds)})

    def _merged(self, feeds: list[str], ctx: Context) -> Iterator[Item]:
        """The items of several feeds, newest first, each once. A feed's next page is asked for only when
        its items so far have all been handed out."""
        state = [{"url": url, "page": 1, "items": [], "done": False} for url in feeds]
        seen: set[str] = set()
        while True:
            for feed in state:
                if not feed["items"] and not feed["done"]:
                    feed["items"] = self._feed_page(feed["url"], feed["page"], ctx)
                    feed["page"] += 1
                    feed["done"] = not feed["items"]
            live = [feed for feed in state if feed["items"]]
            if not live:
                return
            newest = max(live, key=lambda feed: feed["items"][0].published)
            item = newest["items"].pop(0)
            if item.url not in seen:
                seen.add(item.url)
                yield item

    def _feed_page(self, url: str, number: int, ctx: Context) -> list[Item]:
        """One page of a feed, or [] past its end (the site answers 404 there)."""
        try:
            result = self.fetch(set_query_param(url, "paged", number) if number > 1 else url, ctx)
        except FetchError as error:
            if error.status == 404:
                return []
            raise
        items = []
        for entry in feedparser.parse(result.content).entries:
            link = canonical_url(entry.get("link", ""))
            if not link.startswith((f"{HOME}/blog/", f"{HOME}/feature/")):
                continue
            content = entry.get("content") or []
            items.append(Item(
                url=link,
                title=clean(entry.get("title", "")),
                published=parse_date(entry.get("published", "")),
                summary=_teaser(entry.get("summary", "")),
                author=_authors(entry.get("author", "")),
                content_html=content[0].get("value", "") if content else "",
            ))
        return items

    # -- items -----------------------------------------------------------------------------------

    def read_item(self, item: Item, stream: Stream, ctx: Context) -> Extracted:
        page = self.open(item.url, ctx)
        soup = page.soup
        main = soup.select_one("main.main")
        if main is None:
            raise ExtractError(f"{item.url} is not laid out like a National Interest article")

        authors = [clean(link.get_text(" ")) for link in soup.select(".header__meta--taxonomy a[href*='/profile/']")]
        heading = soup.select_one(".header__title")
        title = clean(heading.get_text(" ")) if heading else ""  # read now: the header is cut out below
        published = soup.find("meta", attrs={"property": "article:published_time"})
        image = soup.find("meta", attrs={"property": "og:image"})
        description = soup.find("meta", attrs={"name": "description"})
        tags = _taxonomy(main)

        for selector in CUT:
            for element in main.select(selector):
                element.decompose()
        first = main.find(recursive=False)
        summary = ""
        if first is not None and first.name == "h2":  # the standfirst, above the text: the summary
            summary = clean(first.get_text(" "))
            first.decompose()
        text = element_text(main)
        if not text:
            raise ExtractError(f"{item.url} has no text on its page")
        return Extracted(
            title=title,
            author=", ".join(dict.fromkeys(name for name in authors if name)),
            published=parse_date(published.get("content")) if published else "",
            text=text,
            summary=summary or (clean(description.get("content")) if description else ""),
            image_url=page.link(image.get("content")) if image else "",
            language="en",
            tags=tags,
        )


def _taxonomy(main) -> list[str]:
    """The region, blog, topics and tags the page names under the text, with "Technology" first when the
    item is on one of the site's technology topics or on the Techland blog."""
    found: dict[str, list[str]] = {}
    for row in main.select(".article-taxonomy .article-taxonomy__item"):
        label = row.find("strong")
        if label is None:
            continue
        found[clean(label.get_text()).rstrip(":").lower()] = [clean(link.get_text(" ")) for link in row.find_all("a")]
    topics, blogs = found.get("topic", []), found.get("blog", [])
    technology = ["Technology"] if TECH_BLOG in blogs or any(topic in TECHNOLOGY for topic in topics) else []
    ordered = [*technology, *found.get("region", []), *blogs, *topics, *found.get("tags", [])]
    return list(dict.fromkeys(tag for tag in ordered if tag))


def _teaser(html: str) -> str:
    """A feed item's description, without WordPress's "The post … appeared first on …" line."""
    text = html_to_text(html)
    cut = text.find("The post ")
    if cut > 0 and "appeared first on" in text[cut:]:
        text = text[:cut]
    return clean(text)


def _authors(value: str) -> str:
    """'Nicholas Kruus , Michael O'Hanlon' -> 'Nicholas Kruus, Michael O'Hanlon'."""
    return ", ".join(name for name in (clean(part) for part in value.split(",")) if name)
