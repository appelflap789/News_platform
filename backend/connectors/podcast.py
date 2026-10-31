"""Podcasts: one episode, or every episode of a show.

A podcast is published as a feed (RSS): one entry per episode, with the audio file as its enclosure. That feed
is the open door, made to be fetched by any podcast app, and it is what this connector reads.

Spotify is where a link usually comes from, but Spotify hands out neither the audio nor a transcript: its
developer API has no such thing, and taking either from its player is against its terms. So a Spotify address
is only used to learn *which* episode or show is meant. Its public page says the title, the show, the date and
the length. The show's own feed is then looked up in Apple's podcast directory (the iTunes Search API: public,
no key), which knows the feed of nearly every podcast, and the episode is found in that feed by its title.

A show that exists only on Spotify has no feed. Its episodes are stored with what Spotify's page says about
them (title, date, length, description) and cannot be written out.

What is said in an episode is not collected here; pipeline/videos.py does that after the scrape, from the audio.
The exception is a feed that carries the publisher's own transcript (`<podcast:transcript>`): that is taken
along at once, and nothing has to be listened to.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup

from ..errors import ScrapeError
from ..extractors import Extracted
from ..schemas import FeedRecipe
from ..util import clean, html_to_text, parse_date
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors
from .rss import parse_feed

SPOTIFY = "open.spotify.com"
SPOTIFY_ID = r"[A-Za-z0-9]{22}"
DIRECTORY = "https://itunes.apple.com/search"
PER_PAGE = 10  # episodes of a show handed to the platform at a time: a first scrape takes three such pages
AUDIO = re.compile(r"\.(mp3|m4a|aac|ogg|oga|wav|flac)(\?|$)", re.I)
# Kinds of transcript a feed may offer, the easiest to read first.
TRANSCRIPT_KINDS = ("text/vtt", "application/x-subrip", "application/srt", "application/json", "text/plain", "text/html")
NO_FEED = ("No public feed was found for the show '{show}'. A show that is only on Spotify can be stored with "
           "its title, date and description, but there is no audio to write out.")
NOT_A_PODCAST = ("This Spotify address is not a podcast episode or a show (music cannot be saved here). Open the "
                 "episode in Spotify, choose Share, Copy link, and paste that.")


# --- Spotify: only to learn which episode or show is meant --------------------------------------

def spotify_ref(url: str) -> tuple[str, str] | None:
    """('episode', id), ('show', id), ('track', id)…: what a Spotify address points at, or None for any other."""
    parts = urlsplit(url)
    if (parts.hostname or "").lower() != SPOTIFY:
        return None
    segments = [segment for segment in parts.path.split("/") if segment]
    if segments and segments[0].startswith("intl-"):  # /intl-nl/episode/…
        segments = segments[1:]
    if len(segments) >= 2 and re.fullmatch(SPOTIFY_ID, segments[1]):
        return segments[0], segments[1]
    return None


def is_spotify(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() == SPOTIFY


def spotify_url(kind: str, found_id: str) -> str:
    return f"https://{SPOTIFY}/{kind}/{found_id}"


class _SpotifyPage:
    """A public Spotify page, as far as its head goes: the tags it carries for link previews."""

    def __init__(self, url: str, ctx: Context) -> None:
        self.html = ctx.fetch(url).text
        self.soup = BeautifulSoup(self.html, "lxml")

    def meta(self, key: str) -> str:
        tag = self.soup.find("meta", attrs={"property": key}) or self.soup.find("meta", attrs={"name": key})
        return clean(tag.get("content")) if tag else ""

    def description(self) -> str:
        """The description in full (the meta tag cuts it short), without Spotify's 'Listen to … on Spotify.'"""
        said = self.meta("description")
        for script in self.soup.find_all("script", type="application/ld+json"):
            try:
                said = clean(json.loads(script.string or "").get("description")) or said
            except (ValueError, AttributeError):
                continue
        return re.sub(r"^Listen to [^.]{0,200}? on Spotify\.\s*", "", said)


def spotify_episode(found_id: str, ctx: Context) -> dict:
    """What Spotify's public page says about an episode: title, show, date, length, description, picture."""
    page = _SpotifyPage(spotify_url("episode", found_id), ctx)
    title = page.meta("og:title")
    if not title:
        raise ConnectorError("Spotify shows no episode at this address (it may have been removed).")
    label = page.meta("og:description")  # "The Daily · Episode"
    show = re.search(rf"/show/({SPOTIFY_ID})", page.html)
    return {
        "title": title,
        "show": label.rsplit(" · ", 1)[0] if " · " in label else "",
        "show_id": show.group(1) if show else "",
        "published": parse_date(page.meta("music:release_date")),
        "duration": int(page.meta("music:duration") or 0),
        "description": page.description(),
        "image": page.meta("og:image"),
    }


def spotify_show(found_id: str, ctx: Context) -> dict:
    page = _SpotifyPage(spotify_url("show", found_id), ctx)
    name = page.meta("og:title")
    if not name:
        raise ConnectorError("Spotify shows no podcast at this address.")
    label = page.meta("og:description").split(" · ")  # "Podcast · The New York Times · This is what…"
    return {"name": name, "publisher": label[1] if len(label) > 2 else "", "description": page.description(),
            "image": page.meta("og:image")}


# --- the show's own feed -----------------------------------------------------------------------

def _key(text: str) -> str:
    """A name or title reduced to what makes it the same name: 'The Journal.' and 'the journal' are one."""
    return re.sub(r"[^a-z0-9]+", "", (text or "").casefold())


def _alike(one: str, other: str) -> float:
    return SequenceMatcher(None, _key(one), _key(other)).ratio()


def candidates(show: str, ctx: Context, publisher: str = "") -> list[dict]:
    """The feeds Apple's podcast directory knows for a show of this name, the likeliest first:
    [{name, publisher, feed}]. Empty when it knows none, which is what a Spotify-only show looks like."""
    if not show:
        return []
    answer = ctx.fetch(f"{DIRECTORY}?{urlencode({'media': 'podcast', 'entity': 'podcast', 'limit': 25, 'term': show})}")
    try:
        listed = json.loads(answer.text).get("results", [])
    except ValueError:
        raise ConnectorError("Apple's podcast directory did not answer with a list of shows.") from None
    found = [{"name": clean(entry.get("collectionName")), "publisher": clean(entry.get("artistName")),
              "feed": entry["feedUrl"]} for entry in listed if entry.get("feedUrl")]
    same = [entry for entry in found if _key(entry["name"]) == _key(show)]
    if not same:  # "The X Podcast" on one side and "The X Show" on the other
        same = [entry for entry in found if _alike(entry["name"], show) >= 0.9]
    if publisher:  # two shows of one name: the one by this publisher first (a stable sort keeps Apple's order)
        same.sort(key=lambda entry: _alike(entry["publisher"], publisher) < 0.6)
    return same


@dataclass
class Episode:
    """One entry of a podcast's feed."""

    guid: str
    title: str
    published: str = ""
    duration: int = 0
    description: str = ""  # HTML
    audio_url: str = ""
    audio_type: str = ""
    image: str = ""
    link: str = ""
    transcripts: list[tuple[str, str]] = field(default_factory=list)  # (address, kind)


def seconds(length: str) -> int:
    """'00:33:17' -> 1997, '33:17' -> 1997, '1997' -> 1997"""
    parts = [part for part in str(length or "").strip().split(":") if part.strip().isdigit()]
    total = 0
    for part in parts[:3]:
        total = total * 60 + int(part)
    return total


def _transcripts(feed_text: str) -> dict[str, list[tuple[str, str]]]:
    """guid -> the transcripts the feed offers for that episode. Read from the feed's own text, because the
    feed parser keeps one such tag per entry and a feed may give several kinds."""
    offered: dict[str, list[tuple[str, str]]] = {}
    for entry in re.findall(r"<item\b.*?</item>", feed_text, flags=re.S):
        tags = re.findall(r"<podcast:transcript\b[^>]*>", entry)
        guid = re.search(r"<guid\b[^>]*>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</guid>", entry, flags=re.S)
        if not tags or not guid:
            continue
        found = []
        for tag in tags:
            url = re.search(r'\burl="([^"]+)"', tag)
            kind = re.search(r'\btype="([^"]+)"', tag)
            if url:
                found.append((html_lib.unescape(url.group(1)), (kind.group(1) if kind else "").lower()))
        order = {kind: position for position, kind in enumerate(TRANSCRIPT_KINDS)}
        offered[html_lib.unescape(guid.group(1)).strip()] = sorted(found, key=lambda t: order.get(t[1], len(order)))
    return offered


def episodes(feed_url: str, ctx: Context) -> tuple[dict, list[Episode]]:
    """A show's feed: what it says about the show, and its episodes, newest first."""
    result = ctx.fetch(feed_url, robots=False)  # a feed is published to be fetched, as with RSS
    parsed = parse_feed(result.content, feed_url)
    offered = _transcripts(result.text)
    show_image = (parsed.feed.get("image") or {}).get("href", "")
    show = {"name": clean(parsed.feed.get("title")), "publisher": clean(parsed.feed.get("author")),
            "description": clean(html_to_text(parsed.feed.get("subtitle") or parsed.feed.get("summary") or "")),
            "image": show_image, "link": parsed.feed.get("link", "")}
    listed = []
    for entry in parsed.entries:
        audio = next((enclosure for enclosure in entry.get("enclosures", []) if enclosure.get("href") and (
            enclosure.get("type", "").startswith("audio") or AUDIO.search(enclosure["href"]))), {})
        content = entry.content[0].get("value", "") if entry.get("content") else ""
        guid = entry.get("id") or audio.get("href") or entry.get("link", "")
        if not guid or not entry.get("title"):
            continue
        listed.append(Episode(
            guid=guid, title=clean(entry.get("title")), published=parse_date(entry.get("published", "")),
            duration=seconds(entry.get("itunes_duration", "")), description=content or entry.get("summary", ""),
            audio_url=audio.get("href", ""), audio_type=audio.get("type", ""),
            image=(entry.get("image") or {}).get("href", "") or show_image, link=entry.get("link", ""),
            transcripts=offered.get(guid, [])))
    listed.sort(key=lambda episode: episode.published, reverse=True)
    return show, listed


def _days_apart(one: str, other: str) -> float:
    if not one or not other:
        return 999.0
    return abs((_day(one) - _day(other)).days)


def _day(stamp: str):
    from datetime import date

    return date(int(stamp[:4]), int(stamp[5:7]), int(stamp[8:10]))


def find_episode(listed: list[Episode], title: str, published: str = "", duration: int = 0) -> Episode | None:
    """The entry of a feed that is this episode: by its title, else by its day and length."""
    same = [episode for episode in listed if _key(episode.title) == _key(title)]
    if same:  # a title a show uses more than once ("Weekly update"): the one of that day
        return min(same, key=lambda episode: _days_apart(episode.published, published))
    near = [episode for episode in listed if _days_apart(episode.published, published) <= 1 and duration
            and episode.duration and abs(episode.duration - duration) <= max(90, duration * 0.05)]
    if len(near) == 1:  # the title was edited on one side
        return near[0]
    close = [(_alike(episode.title, title), episode) for episode in listed
             if _days_apart(episode.published, published) <= 3 or not published]
    best = max(close, key=lambda pair: pair[0], default=(0.0, None))
    return best[1] if best[0] >= 0.8 else None


# --- a publisher's own transcript ----------------------------------------------------------------

def _stamp(at: float) -> str:
    at = int(at)
    return f"[{at // 3600}:{at % 3600 // 60:02d}:{at % 60:02d}]" if at >= 3600 else f"[{at // 60:02d}:{at % 60:02d}]"


def _clock(text: str) -> float:
    """'00:01:02.500' or '01:02,500' -> seconds"""
    total = 0.0
    for part in text.replace(",", ".").split(":"):
        total = total * 60 + float(part)
    return total


def _paragraphs(cues: list[tuple[float, str, str]]) -> str:
    """Cues of a few words each (start, speaker, text) joined into paragraphs that begin with their time."""
    out: list[str] = []
    start, speaker, words = 0.0, "", []
    for at, who, text in cues:
        text = clean(re.sub(r"<[^>]+>", "", text))
        if not text:
            continue
        if words and ((who and who != speaker) or sum(len(word) + 1 for word in words) > 500 or at - start > 90):
            out.append(f"{_stamp(start)} {speaker + ': ' if speaker else ''}{' '.join(words)}")
            words = []
        if not words:
            start, speaker = at, who or speaker
        words.append(text)
    if words:
        out.append(f"{_stamp(start)} {speaker + ': ' if speaker else ''}{' '.join(words)}")
    return "\n\n".join(out)


def transcript_text(content: str, kind: str = "") -> str:
    """A transcript as a feed offers it (WebVTT, SRT, the podcast JSON format, HTML or plain text) as the
    plain text with times that the rest of the platform works with."""
    content = content.lstrip("﻿").strip()
    if kind == "application/json" or content.startswith("{"):
        try:
            segments = json.loads(content).get("segments", [])
        except ValueError:
            segments = []
        return _paragraphs([(float(segment.get("startTime") or 0), clean(segment.get("speaker")),
                             str(segment.get("body") or "")) for segment in segments])
    if "-->" in content:  # WebVTT or SRT: blocks of "start --> end" and the words under it
        cues = []
        for block in re.split(r"\n\s*\n", content.replace("\r", "")):
            lines = block.strip().split("\n")
            timing = next((index for index, line in enumerate(lines) if "-->" in line), None)
            if timing is None:
                continue
            said = " ".join(lines[timing + 1:])
            voice = re.match(r"<v\s+([^>]+)>", said)  # WebVTT names a speaker as <v Name>
            try:
                cues.append((_clock(lines[timing].split("-->")[0].strip()), voice.group(1) if voice else "", said))
            except ValueError:
                continue
        return _paragraphs(cues)
    if kind == "text/html" or re.match(r"<(!doctype|html|p|div)\b", content, re.I):
        return html_to_text(content)
    return "\n\n".join(clean(paragraph) for paragraph in re.split(r"\n\s*\n", content) if clean(paragraph))


# --- the connector -----------------------------------------------------------------------------------

def describe(url: str, ctx: Context) -> dict:
    """Name, feed, description and picture of the show behind a Spotify address (of the show, or of one of its
    episodes), for the recipe of a new source. Raises ConnectorError when the show has no public feed."""
    ref = spotify_ref(url)
    if ref is None or ref[0] not in ("show", "episode"):
        raise ConnectorError(NOT_A_PODCAST)
    show_id = ref[1] if ref[0] == "show" else spotify_episode(ref[1], ctx)["show_id"]
    if not show_id:
        raise ConnectorError("Spotify's page does not say which show this episode belongs to.")
    about = spotify_show(show_id, ctx)
    found = candidates(about["name"], ctx, about["publisher"])
    if not found:
        raise ConnectorError(NO_FEED.format(show=about["name"]))
    show, listed = episodes(found[0]["feed"], ctx)
    return {"name": about["name"], "homepage": spotify_url("show", show_id), "feed": found[0]["feed"],
            "publisher": about["publisher"] or show["publisher"], "description": about["description"] or show["description"],
            "icon_url": about["image"] or show["image"], "episodes": len(listed)}


def _as_html(text: str) -> str:
    return "".join(f"<p>{html_lib.escape(line)}</p>" for line in (text or "").split("\n") if line.strip())


def _item(url: str, episode: Episode, show: str) -> Item:
    extra = {"podcast": "yes", "duration": str(episode.duration)}
    if episode.audio_url:
        extra.update(audio_url=episode.audio_url, audio_type=episode.audio_type)
    if episode.transcripts:
        extra.update(transcript_url=episode.transcripts[0][0], transcript_kind=episode.transcripts[0][1])
    return Item(url=url, title=episode.title, published=episode.published, author=show, image_url=episode.image,
                content_html=episode.description, extra=extra)


@connectors.register
class PodcastConnector(Connector):
    name = "podcast"
    label = "Podcast"
    description = (
        "The episodes of a podcast, from the show's own feed. Takes the address of the feed, or a Spotify "
        "address of a show or of one episode (Spotify is then only used to find the show's feed). Collects "
        "title, show, date, length, description and the address of the audio. What is said in an episode is "
        "written out afterwards, when a Gemini API key is set."
    )
    for_analysis = False  # Quick detect recognises a Spotify address by itself; there is nothing to work out
    newest_first = True  # the episodes are sorted newest first

    def opens_items(self, feed: FeedRecipe) -> bool:
        return True  # read_item downloads nothing, unless the feed offers a transcript

    def iter_pages(self, feed: FeedRecipe, ctx: Context) -> Iterator[ListPage]:
        ref = spotify_ref(feed.url)
        if ref and ref[0] == "episode":
            yield ListPage([self._one(ref[1], ctx)], feed.url, {"door": "one episode, found in its show's feed"})
            return
        if is_spotify(feed.url):
            feed_url = describe(feed.url, ctx)["feed"]
        else:
            feed_url = feed.url
        show, listed = episodes(feed_url, ctx)
        # An episode is known by its own page when the feed gives each one a page; many feeds give every
        # episode the same link (the show's site), and then by the feed's address and the episode's id.
        links = [episode.link for episode in listed]
        items = []
        for episode in listed:
            own_page = episode.link and links.count(episode.link) == 1 and episode.link != show["link"]
            items.append(_item(episode.link if own_page else f"{feed_url}#{episode.guid}", episode, show["name"]))
        for start in range(0, len(items), PER_PAGE):
            yield ListPage(items[start:start + PER_PAGE], feed_url, {"door": "the show's feed", "episodes": len(items)})

    def _one(self, found_id: str, ctx: Context) -> Item:
        """One episode by its Spotify address: what Spotify's page says, completed from the show's feed."""
        about = spotify_episode(found_id, ctx)
        episode = Episode(guid=found_id, title=about["title"], published=about["published"],
                          duration=about["duration"], description=_as_html(about["description"]), image=about["image"])
        why = NO_FEED.format(show=about["show"])
        try:
            for candidate in candidates(about["show"], ctx)[:3]:  # two shows of one name: the one that has it
                found = find_episode(episodes(candidate["feed"], ctx)[1], about["title"], about["published"],
                                     about["duration"])
                if found:
                    episode.audio_url, episode.audio_type = found.audio_url, found.audio_type
                    episode.transcripts = found.transcripts
                    episode.description = found.description or episode.description
                    break
                why = (f"The feed of '{about['show']}' does not carry this episode (feeds often hold only the "
                       f"latest ones), so there is no audio to write out.")
        except ScrapeError as error:  # the directory or the feed did not answer: the episode is still worth storing
            why = f"The show's feed could not be read ({error}), so there is no audio to write out."
        item = _item(spotify_url("episode", found_id), episode, about["show"])
        if not episode.audio_url:
            item.extra["no_audio"] = why
        return item

    def read_item(self, item: Item, feed: FeedRecipe, ctx: Context) -> Extracted:
        """The description of an episode as its text, for as long as there is no transcript, and the
        publisher's own transcript when the feed offers one."""
        if item.extra.get("transcript_url") and "transcript" not in item.extra:
            try:
                offered = ctx.fetch(item.extra["transcript_url"], robots=False)
                said = transcript_text(offered.text, item.extra.get("transcript_kind", ""))
                if len(said) > 500:
                    item.extra["transcript"] = said
            except ScrapeError:
                pass  # then the audio is listened to instead
        return Extracted(title=item.title, author=item.author, published=item.published, image_url=item.image_url,
                         text=html_to_text(item.content_html), content_type="podcast")
