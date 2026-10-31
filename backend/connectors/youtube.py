"""YouTube: the videos of a channel, or one video.

What is collected per video: title, channel, upload date, description, thumbnail, length and the number of
views. What is *said* in the video is not collected here: YouTube's own API gives a transcript only to the
owner of a video. That part is done after the scrape, by pipeline/videos.py.

There are two doors, and the connector takes the better one that is open:

* **With a YouTube API key** (Settings; free from Google): the official YouTube Data API. It finds a channel
  by its @name, lists every video the channel ever uploaded, fifty to a page, and gives length and views for
  all of them. One page costs 2 of the 10,000 units a key may use per day.
* **Without a key**: the channel's public feed, which carries its 15 newest videos, and each video's own page
  for the length. A channel can then only be given by its /channel/UC... address or by one of its videos,
  because YouTube shows visitors from Europe a consent page instead of the channel page, and the platform does
  not click such pages away.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Iterator
from urllib.parse import parse_qs, urlencode, urlsplit

from .. import config
from ..extractors import Extracted, ExtractError
from ..fetchers import FetchError
from ..registry import Field
from ..schemas import FeedRecipe
from ..util import clean, parse_date, registrable_domain
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors
from .rss import parse_feed

API = "https://www.googleapis.com/youtube/v3"
HOSTS = {"youtube.com", "youtu.be", "youtube-nocookie.com"}
VIDEO_ID = r"[A-Za-z0-9_-]{11}"
PAGE_SIZE = 50  # the most the API gives per request
# YouTube keeps a playlist behind each tab of a channel's page. "UULF" plus the channel's id without its "UC"
# is the Videos tab: the regular videos, without Shorts and without live streams. ("UU" is everything.)
VIDEOS_TAB = "UULF"
ONLY_SHORTS = ("This channel has no regular videos, only Shorts or live streams. To collect those, set the feed's "
               "Shorts option to yes on the source's Structure tab.")
ARCHIVE_PAGES = 400  # a deep scrape may walk this many pages: 20,000 videos
NOT_YET = ("upcoming", "live")  # a premiere or stream that has not ended has nothing to read yet
NO_KEY = ("Without a YouTube API key a channel can only be followed by its /channel/UC... address, or by pasting "
          "the address of one of its videos. Add a YouTube API key in Settings (free from Google) to add a "
          "channel by its @name and to get all of its videos instead of the 15 newest.")


def is_youtube(url: str) -> bool:
    return registrable_domain(urlsplit(url).hostname or "") in HOSTS


def video_id(url: str) -> str:
    """The id of the video an address points at, or '' when it is not the address of a video."""
    parts = urlsplit(url)
    if not is_youtube(url):
        return ""
    path = parts.path.strip("/")
    if registrable_domain(parts.hostname or "") == "youtu.be":
        found = path.split("/")[0]
    elif path == "watch":
        found = parse_qs(parts.query).get("v", [""])[0]
    else:
        match = re.match(rf"(?:shorts|live|embed|v)/({VIDEO_ID})(?:/|$)", path)
        found = match.group(1) if match else ""
    return found if re.fullmatch(VIDEO_ID, found) else ""


def channel_ref(url: str) -> tuple[str, str] | None:
    """How an address names a channel: ('id', 'UC...'), ('handle', '@name'), ('user', name) or ('custom', name)."""
    if not is_youtube(url) or video_id(url):
        return None
    segments = [segment for segment in urlsplit(url).path.split("/") if segment]
    if not segments:
        return None
    if segments[0].startswith("@"):
        return "handle", segments[0]
    if len(segments) > 1 and segments[0] in ("channel", "user", "c"):
        return {"channel": "id", "user": "user", "c": "custom"}[segments[0]], segments[1]
    return None


def watch_url(found_id: str) -> str:
    return f"https://www.youtube.com/watch?v={found_id}"


def seconds(duration: str) -> int:
    """'PT1H2M3S' -> 3723"""
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not match:
        return 0
    days, hours, minutes, secs = (int(part or 0) for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + secs


def _in_page(page: str, key: str) -> str:
    """The value of a "key":"value" pair inside the data a video page carries, unescaped."""
    match = re.search(rf'"{key}":("(?:[^"\\]|\\.)*")', page)
    if not match:
        return ""
    try:
        return json.loads(match.group(1))
    except ValueError:
        return ""


def parse_watch(page: str) -> dict:
    """What a video's own page says about it. Every value may be missing."""

    def meta(name: str) -> str:
        match = re.search(rf'<meta\s+(?:itemprop|property|name)="{re.escape(name)}"\s+content="([^"]*)"', page)
        return html_lib.unescape(match.group(1)) if match else ""

    return {
        "title": meta("og:title"),
        "published": parse_date(meta("datePublished") or meta("uploadDate")),
        "duration": int(_in_page(page, "lengthSeconds") or 0) or seconds(meta("duration")),
        "views": int(_in_page(page, "viewCount") or 0),
        "description": _in_page(page, "shortDescription") or meta("og:description"),
        "channel": _in_page(page, "ownerChannelName") or _in_page(page, "author"),
        "channel_id": _in_page(page, "channelId"),
        "thumbnail": meta("og:image"),
        "live": '"isLiveNow":true' in page or '"isUpcoming":true' in page,
    }


def as_html(text: str) -> str:
    """A description as the HTML the rest of the pipeline expects from a listing."""
    return "".join(f"<p>{html_lib.escape(line)}</p>" for line in (text or "").split("\n") if line.strip())


def _thumbnail(thumbnails: dict) -> str:
    for size in ("maxres", "standard", "high", "medium", "default"):
        if thumbnails.get(size, {}).get("url"):
            return thumbnails[size]["url"]
    return ""


def api(ctx: Context, path: str, missing_ok: bool = False, **params) -> dict | None:
    """One request to the YouTube Data API. The key never ends up in an error message or a log.
    With `missing_ok`, what does not exist (a channel without a Videos tab) is None instead of an error."""
    key = config.other_key("youtube")
    try:
        result = ctx.fetch(f"{API}/{path}?{urlencode({**params, 'key': key})}", robots=False)
        return json.loads(result.text)
    except FetchError as error:
        if error.status == 404 and missing_ok:
            return None
        if error.status in (400, 401, 403):
            raise ConnectorError(
                f"The YouTube API refused the request (HTTP {error.status}). The key may be wrong, the 'YouTube "
                f"Data API v3' may not be switched on for it in Google Cloud, or today's quota may be used up."
            ) from None
        raise ConnectorError(f"The YouTube API could not be reached ({str(error).replace(key, '…')}).") from None
    except ValueError:
        raise ConnectorError("The YouTube API sent an answer that could not be read.") from None


def find_channel(ctx: Context, ref: tuple[str, str]) -> dict:
    """The channel an address names, through the API: its id, name, description, picture, uploads playlist."""
    kind, value = ref
    tries = {"id": [("id", value)], "handle": [("forHandle", value)], "user": [("forUsername", value)],
             "custom": [("forHandle", value), ("forUsername", value)]}[kind]
    for parameter, wanted in tries:
        found = api(ctx, "channels", part="snippet,contentDetails,statistics", **{parameter: wanted}).get("items")
        if found:
            channel = found[0]
            snippet = channel.get("snippet", {})
            return {
                "id": channel["id"],
                "name": clean(snippet.get("title", "")),
                "description": clean(snippet.get("description", "")),
                "icon_url": _thumbnail(snippet.get("thumbnails", {})),
                "uploads": channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                or "UU" + channel["id"][2:],
                "videos": int(channel.get("statistics", {}).get("videoCount") or 0),
            }
    raise ConnectorError(f"YouTube knows no channel called {value}.")


def describe(url: str, ctx: Context) -> dict:
    """Name, address, description and picture of the channel (or the channel of the video) behind an address,
    for the recipe of a new source. Raises ConnectorError when the address cannot be followed."""
    found_id = video_id(url)
    if config.other_key("youtube"):
        if found_id:
            listed = api(ctx, "videos", part="snippet", id=found_id).get("items")
            if not listed:
                raise ConnectorError("YouTube knows no video at this address.")
            ref = ("id", listed[0]["snippet"]["channelId"])
        else:
            ref = channel_ref(url)
            if ref is None:
                raise ConnectorError("This is not the address of a YouTube channel or video.")
        channel = find_channel(ctx, ref)
        return {"name": channel["name"], "homepage": f"https://www.youtube.com/channel/{channel['id']}",
                "description": channel["description"], "icon_url": channel["icon_url"], "videos": channel["videos"]}
    if found_id:
        page = parse_watch(ctx.fetch(watch_url(found_id)).text)
        if not page["channel_id"]:
            raise ConnectorError("The video's page does not say which channel it belongs to. " + NO_KEY)
        ref, name = ("id", page["channel_id"]), page["channel"]
    else:
        ref, name = channel_ref(url), ""
        if ref is None or ref[0] != "id":
            raise ConnectorError(NO_KEY)
    if not name:
        feed = parse_feed(ctx.fetch(_feed_url(ref[1]), robots=False).content, url)
        name = clean(feed.feed.get("title", "")) or ref[1]
    return {"name": name, "homepage": f"https://www.youtube.com/channel/{ref[1]}", "description": "",
            "icon_url": "https://www.youtube.com/favicon.ico", "videos": 0}


def _feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _item(found_id: str, *, title: str, published: str, channel: str, description: str, thumbnail: str,
          views: int | None = None, duration: int | None = None, tags: list[str] | None = None,
          short: bool = False) -> Item:
    extra = {"video_id": found_id}
    if short:
        extra["short"] = "yes"
    if views is not None:
        extra["views"] = str(views)
    if duration is not None:
        extra["duration"] = str(duration)
    return Item(url=watch_url(found_id), title=clean(title), published=parse_date(published), author=clean(channel),
                image_url=thumbnail or f"https://i.ytimg.com/vi/{found_id}/hqdefault.jpg",
                content_html=as_html(description), tags=[clean(tag) for tag in (tags or [])[:10]], extra=extra)


@connectors.register
class YouTubeConnector(Connector):
    name = "youtube"
    label = "YouTube"
    description = (
        "A YouTube channel (https://www.youtube.com/@name or /channel/UC...) or one video. Collects title, "
        "channel, upload date, description, length and views. With a YouTube API key (Settings) every video of "
        "the channel is listed; without one, the 15 newest. Shorts are left out unless the option says "
        "otherwise. What is said in a video is written out afterwards, when a Gemini API key is set."
    )
    fields = [
        Field("shorts", "Shorts", type="select", choices=("no", "yes"),
              help="no (the default) = only the channel's regular videos, as on its Videos tab: no Shorts and no "
                   "live streams. yes = everything the channel uploaded."),
    ]
    for_analysis = False  # Quick detect recognises YouTube by itself; there is nothing for Claude to work out
    newest_first = True  # a channel's uploads come newest first

    def opens_items(self, feed: FeedRecipe) -> bool:
        return True  # read_item only downloads something when the listing did not say everything

    def page_limit(self, feed: FeedRecipe, deep: bool) -> int:
        return ARCHIVE_PAGES if deep else 0

    # -- listing --------------------------------------------------------------------------

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        found_id = video_id(feed.url)
        if found_id:
            yield ListPage(self._videos(ctx, [found_id]) if config.other_key("youtube")
                           else [Item(url=watch_url(found_id), extra={"video_id": found_id})],
                           feed.url, {"door": "one video"})
            return
        ref = channel_ref(feed.url)
        if ref is None:
            raise ConnectorError("Give a channel (https://www.youtube.com/@name) or a video "
                                 "(https://www.youtube.com/watch?v=...).")
        everything = feed.opt("shorts", "no") == "yes"
        if config.other_key("youtube"):
            yield from self._through_api(ctx, ref, feed.url, everything)
        elif ref[0] == "id":
            yield self._through_feed(ctx, ref[1], everything)
        else:
            raise ConnectorError(NO_KEY)

    def _through_api(self, ctx: Context, ref: tuple[str, str], url: str, everything: bool) -> Iterator[ListPage]:
        channel = find_channel(ctx, ref)
        playlist = channel["uploads"] if everything else VIDEOS_TAB + channel["id"][2:]
        token = ""
        while True:
            page = api(ctx, "playlistItems", missing_ok=not everything, part="contentDetails", playlistId=playlist,
                       maxResults=PAGE_SIZE, **({"pageToken": token} if token else {}))
            if page is None:
                yield ListPage([], url, {"door": "YouTube Data API", "note": ONLY_SHORTS})
                return
            ids = [entry["contentDetails"]["videoId"] for entry in page.get("items", [])
                   if entry.get("contentDetails", {}).get("videoId")]
            yield ListPage(self._videos(ctx, ids) if ids else [], url,
                           {"door": "YouTube Data API", "listed": len(ids), "of": page.get("pageInfo", {}).get("totalResults")})
            token = page.get("nextPageToken", "")
            if not token or not ids:
                return

    def _videos(self, ctx: Context, ids: list[str]) -> list[Item]:
        """Full details of up to fifty videos, in the order asked. Deleted and private ones drop out."""
        listed = api(ctx, "videos", part="snippet,contentDetails,statistics", id=",".join(ids)).get("items", [])
        by_id = {entry["id"]: entry for entry in listed}
        items = []
        for found_id in ids:
            entry = by_id.get(found_id)
            if entry is None or entry["snippet"].get("liveBroadcastContent") in NOT_YET:
                continue
            snippet = entry["snippet"]
            items.append(_item(
                found_id, title=snippet.get("title", ""), published=snippet.get("publishedAt", ""),
                channel=snippet.get("channelTitle", ""), description=snippet.get("description", ""),
                thumbnail=_thumbnail(snippet.get("thumbnails", {})), tags=snippet.get("tags"),
                views=int(entry.get("statistics", {}).get("viewCount") or 0),
                duration=seconds(entry.get("contentDetails", {}).get("duration", ""))))
        return items

    def _through_feed(self, ctx: Context, channel_id: str, everything: bool) -> ListPage:
        if not everything:
            try:  # the feed of the Videos tab: fifteen regular videos, not fifteen uploads of which half are Shorts
                return ListPage(self._feed_items(ctx, f"https://www.youtube.com/feeds/videos.xml?playlist_id="
                                                      f"{VIDEOS_TAB}{channel_id[2:]}"),
                                _feed_url(channel_id), {"door": "the feed of the channel's Videos tab (its 15 newest)"})
            except FetchError as error:
                if error.status != 404:
                    raise  # no such feed: the channel's own feed says per entry whether it is a Short
        items = self._feed_items(ctx, _feed_url(channel_id))
        report = {"door": "the channel's feed (its 15 newest uploads)", "listed": len(items)}
        if not everything:
            items = [item for item in items if "short" not in item.extra]
            if not items:
                report["note"] = ONLY_SHORTS
        return ListPage(items, _feed_url(channel_id), report)

    @staticmethod
    def _feed_items(ctx: Context, url: str) -> list[Item]:
        parsed = parse_feed(ctx.fetch(url, robots=False).content, url)  # a feed you subscribed to, as with RSS
        items = []
        for entry in parsed.entries:
            found_id = entry.get("yt_videoid") or video_id(entry.get("link", ""))
            if not found_id:
                continue
            thumbnails = entry.get("media_thumbnail") or [{}]
            items.append(_item(
                found_id, title=entry.get("title", ""), published=entry.get("published", ""),
                channel=entry.get("author", "") or parsed.feed.get("title", ""),
                description=entry.get("summary", ""), thumbnail=thumbnails[0].get("url", ""),
                views=int((entry.get("media_statistics") or {}).get("views") or 0),
                short="/shorts/" in entry.get("link", "")))
        return items

    # -- one video ------------------------------------------------------------------------

    def read_item(self, item: Item, feed: FeedRecipe, ctx: Context) -> Extracted:
        """The description of a video as its text, for as long as there is no transcript. Its own page is
        only opened when the listing did not give the length (the feed does not, nor does a pasted address)."""
        extracted = Extracted(content_type="video")
        if "duration" not in item.extra:
            page = parse_watch(ctx.fetch(item.url, feed.fetcher).text)
            if not (page["title"] or item.title):
                raise ExtractError(f"{item.url} is not a video that can be opened (it may be private or removed)")
            if page["live"]:
                raise ExtractError(f"{item.url} is a live stream or premiere that has not ended yet")
            item.extra["duration"] = str(page["duration"])
            if page["views"] or "views" not in item.extra:
                item.extra["views"] = str(page["views"])
            item.title = item.title or clean(page["title"])
            item.author = item.author or clean(page["channel"])
            item.published = item.published or page["published"]
            item.image_url = item.image_url or page["thumbnail"]
            if not item.content_html:
                item.content_html = as_html(page["description"])
            extracted.title, extracted.author, extracted.published = item.title, item.author, item.published
            extracted.image_url = item.image_url
        extracted.text = "\n\n".join(line for line in re.sub(r"<[^>]+>", "\n", item.content_html).split("\n")
                                     if line.strip())
        extracted.text = html_lib.unescape(extracted.text)
        return extracted
