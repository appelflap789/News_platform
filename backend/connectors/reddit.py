"""Reddit: a subreddit, a user, or a search, read through Reddit's public Atom feeds.

A feed collects one of two things, chosen with its `collect` option:

- `posts`: every post, with its own text and the link it shares. When `comments` is set, the post's
  highest-voted comments are read from the post's own feed and stored under it.
- `articles`: only the posts that share an article. What is stored is the article itself, read from the site
  it is on. The post gives the title and the date, and a closing line says where the article was shared.

Reddit gives a client without an account very few requests: one a minute when this was written. It says so
in `x-ratelimit-*` headers, which the fetcher obeys. A listing page of 25 posts is one request, and so is
every post whose comments are read.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from html import escape
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..errors import ScrapeError
from ..extractors import Extracted, ExtractError, pick
from ..registry import Field
from ..schemas import FeedRecipe
from ..util import (absolutize, canonical_url, clean, host_of, html_to_text, parse_date, registrable_domain,
                    set_query_param, word_count)
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors
from .rss import parse_feed

COLLECT = ("posts", "articles")
MAX_COMMENTS = 100
LISTING_TTL = 120.0  # seconds a downloaded listing page is reused
MIN_ARTICLE_WORDS = 60  # a page with less text than this is a paywall or a consent screen, not the article
# Links that lead to something to look at or to another network, not to something to read.
NOT_ARTICLES = {
    "reddit.com", "redd.it", "redditmedia.com", "imgur.com", "giphy.com", "gfycat.com", "youtube.com", "youtu.be",
    "vimeo.com", "streamable.com", "twitch.tv", "tiktok.com", "spotify.com", "twitter.com", "x.com", "t.co",
    "instagram.com", "facebook.com", "fb.watch", "threads.net", "bsky.app", "linkedin.com", "t.me", "discord.gg",
    "discord.com",
}
MEDIA_FILE = re.compile(r"\.(jpe?g|png|gifv?|webp|mp4|webm|mov)$", re.I)
NO_COMMENT = {"", "[deleted]", "[removed]"}
DISCUSSION = re.compile(r"https://www\.reddit\.com/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+(?:/[^\s<>\"')]*)?")


def feed_url(url: str) -> str:
    """https://reddit.com/r/drones/top?t=week -> https://www.reddit.com/r/drones/top/.rss?t=week"""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if path.endswith(".rss"):
        path = path[: -len(".rss")].rstrip("/")
    if not path:
        raise ConnectorError("Give a subreddit, user or search URL, e.g. https://www.reddit.com/r/drones")
    return urlunsplit(("https", "www.reddit.com", f"{path}/.rss", parts.query, ""))


def comments_url(post_url: str, count: int) -> str:
    """The feed of a post's top-level comments, highest voted first."""
    path = urlsplit(post_url).path.rstrip("/")
    return urlunsplit(("https", "www.reddit.com", f"{path}/.rss", f"sort=top&depth=1&limit={count + 1}", ""))


def discussion_url(*texts: str) -> str:
    """The Reddit post an item belongs to: the item's own address when it is a post, or the address in the
    line "Shared in r/… by u/…: …" that closes an article which was shared there. '' for any other item."""
    for text in texts:
        found = DISCUSSION.search(text or "")
        if found:
            return found.group(0)
    return ""


def read_comments(post_url: str, count: int, ctx: Context, fetcher: str = "http") -> list[tuple[str, str]]:
    """A post's top-level comments, highest voted first: (who, what they wrote). One request to Reddit."""
    url = comments_url(post_url, count)
    parsed = parse_feed(ctx.fetch(url, fetcher, robots=False).content, url)
    comments = []
    for entry in parsed.entries:
        author = clean(entry.get("author", "")).removeprefix("/u/")
        if not entry.get("id", "").startswith("t1_") or author == "AutoModerator":
            continue  # the first entry is the post itself
        text = html_to_text(entry.content[0].get("value", "") if entry.get("content") else "")
        if text not in NO_COMMENT:
            comments.append((author, text))
    return comments[:count]


def shares_an_article(link: str) -> bool:
    parts = urlsplit(link)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    return registrable_domain(parts.hostname) not in NOT_ARTICLES and not MEDIA_FILE.search(parts.path)


@dataclass
class Post:
    """One entry of a listing feed."""

    url: str  # the post on Reddit
    title: str
    author: str  # without the u/
    published: str
    body_html: str  # the post's own text; '' when the post is only a link
    link: str  # the outside address the post shares; '' for a text post
    image_url: str
    tags: list[str]

    @property
    def place(self) -> str:
        """'r/geopolitics', from the post's address."""
        found = re.match(r"/(r/[^/]+)/", urlsplit(self.url).path)
        return found.group(1) if found else "Reddit"


def read_post(entry, base_url: str) -> Post | None:
    url = absolutize(base_url, entry.get("link", ""))
    if not url:
        return None
    url = canonical_url(url)
    content = entry.content[0].get("value", "") if entry.get("content") else entry.get("summary", "")
    soup = BeautifulSoup(content, "lxml")
    # Under every entry Reddit writes "submitted by /u/name [link] [comments]"; [link] is what the post shares,
    # and for a text post that is the post itself.
    shared = next((absolutize(base_url, a["href"]) for a in soup.find_all("a", href=True)
                   if clean(a.get_text()) == "[link]"), "")
    body = soup.select_one("div.md")
    image = next((m["url"] for m in entry.get("media_thumbnail", []) or [] if m.get("url")), "")
    if not image and soup.find("img", src=True):
        image = soup.find("img", src=True)["src"]
    return Post(
        url=url,
        title=clean(html_to_text(entry.get("title", ""))),
        author=clean(entry.get("author", "")).removeprefix("/u/"),
        published=parse_date(entry.get("published_parsed") or entry.get("updated_parsed")
                             or entry.get("published") or entry.get("updated")),
        body_html=str(body) if body else "",
        link="" if not shared or canonical_url(shared) == url else shared,
        image_url=absolutize(base_url, image),
        tags=[clean(t.get("term", "")) for t in entry.get("tags", []) if t.get("term")],
    )


@connectors.register
class RedditConnector(Connector):
    name = "reddit"
    label = "Reddit"
    description = (
        "A subreddit (https://www.reddit.com/r/<name>, optionally /new, /top, /hot), a user or a search, read "
        "through Reddit's public feeds. Collects either the posts themselves, with their comments if wanted, or "
        "the articles that the posts share. Reddit allows about one request a minute: a page of 25 posts is one "
        "request, and so is every post whose comments are read. The switch for opening item pages is not used."
    )
    fields = [
        Field("collect", "Collect", type="select", choices=COLLECT,
              help="posts = every post, with its own text and the link it shares. articles = only posts that "
                   "share an article; the article itself is opened on its own site and stored. Default: posts."),
        Field("comments", "Comments per post", type="number",
              help=f"How many comments to store under each item, highest voted first (0 to {MAX_COMMENTS}). "
                   "Empty = none. Costs one extra request, so about a minute, per item."),
    ]
    inline_content = True

    def __init__(self) -> None:
        self._listings: dict[str, tuple[float, bytes, str]] = {}

    # -- listing --------------------------------------------------------------------------

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        collect = self._collect(feed)
        url = feed_url(feed.url)
        seen: set[str] = set()
        listed: set[str] = set()
        while url:
            content, final_url = self._listing(url, feed, ctx)
            parsed = parse_feed(content, url)
            posts = [post for post in (read_post(entry, final_url) for entry in parsed.entries)
                     if post and post.url not in seen]
            seen.update(post.url for post in posts)
            items = []
            for post in posts:
                if collect == "articles" and not shares_an_article(post.link):
                    continue
                item = self._item(post, collect)
                if item.url not in listed:  # the same article is often posted twice
                    listed.add(item.url)
                    items.append(item)
            report: dict = {"entries_in_feed": len(parsed.entries)}
            if collect == "articles":
                report["sharing_an_article"] = len(items)
                if posts and not items:
                    report["note"] = (f"none of the {len(posts)} posts on this page shares an article (they are "
                                      "text, picture or video posts); set this feed to collect posts instead")
            yield ListPage(items, final_url, report)
            last_id = parsed.entries[-1].get("id", "") if parsed.entries else ""
            if not posts or not last_id:
                return
            url = set_query_param(feed_url(feed.url), "after", last_id)

    def _listing(self, url: str, feed: FeedRecipe, ctx: Context) -> tuple[bytes, str]:
        """A listing page. It is kept for two minutes, so that two feeds on the same subreddit, or a test in
        the editor followed by a scrape, do not each spend one of the few requests Reddit allows."""
        now = time.monotonic()
        cached = self._listings.get(url)
        if cached and now - cached[0] < LISTING_TTL:
            return cached[1], cached[2]
        result = ctx.fetch(url, feed.fetcher, robots=False)
        self._listings = {key: kept for key, kept in self._listings.items() if now - kept[0] < LISTING_TTL}
        self._listings[url] = (now, result.content, result.url)
        return result.content, result.url

    def forget(self) -> None:
        """Drop the kept listing pages."""
        self._listings.clear()

    @staticmethod
    def _item(post: Post, collect: str) -> Item:
        shared = f"Shared in {post.place} by u/{post.author}: {post.url}"
        if collect == "articles":
            return Item(
                url=canonical_url(post.link),
                title=post.title,
                published=post.published,  # when it was shared; the author is left to the article's own page
                image_url=post.image_url,
                tags=post.tags,
                # what is stored when the article's own page cannot be read
                content_html=f"{post.body_html}<p>{escape(shared)}</p>",
                extra={"post": post.url, "shared": shared},
            )
        link = f"<p>Link: {escape(post.link)}</p>" if post.link else ""
        return Item(url=post.url, title=post.title, published=post.published, author=post.author,
                    image_url=post.image_url, tags=post.tags, content_html=post.body_html + link)

    # -- items ----------------------------------------------------------------------------

    def opens_items(self, feed: FeedRecipe) -> bool:
        return self._collect(feed) == "articles" or self._comment_count(feed) > 0

    def read_item(self, item: Item, feed: FeedRecipe, ctx: Context) -> Extracted:
        if self._collect(feed) == "posts":
            post = html_to_text(item.content_html)
            return Extracted(text="\n\n".join(part for part in (post, self._comments(item.url, feed, ctx)) if part))

        result = ctx.fetch(item.url, feed.fetcher)
        extracted = pick(result).extract(result, {}, ctx)
        if word_count(extracted.text) < MIN_ARTICLE_WORDS:
            raise ExtractError(f"{host_of(result.url)} shows a scraper almost no text: a paywall, a consent "
                               f"screen, or a page that only works with JavaScript")
        parts = [extracted.text, item.extra.get("shared", "")]
        if self._comment_count(feed) and item.extra.get("post"):
            try:
                parts.append(self._comments(item.extra["post"], feed, ctx))
            except ScrapeError:
                pass  # the article is what this feed is for; it is complete without the discussion
        extracted.text = "\n\n".join(part for part in parts if part)
        return extracted

    def _comments(self, post_url: str, feed: FeedRecipe, ctx: Context) -> str:
        """A post's top-level comments as text, one paragraph each, or '' when there are none."""
        comments = [f"u/{author}: {text}" for author, text in
                    read_comments(post_url, self._comment_count(feed), ctx, feed.fetcher)]
        if not comments:
            return ""
        return "\n\n".join([f"Comments on Reddit, highest voted first ({len(comments)})", *comments])

    # -- options --------------------------------------------------------------------------

    @staticmethod
    def _collect(feed: FeedRecipe) -> str:
        collect = feed.opt("collect", "posts")
        if collect not in COLLECT:
            raise ConnectorError(f"'collect' must be one of {', '.join(COLLECT)}, not '{collect}'")
        return collect

    @staticmethod
    def _comment_count(feed: FeedRecipe) -> int:
        return max(0, min(feed.opt_int("comments", 0), MAX_COMMENTS))
