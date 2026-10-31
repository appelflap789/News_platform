"""Podcasts: a Spotify address only says which episode is meant; the episode comes from the show's own feed.

The Spotify pages, the directory's answer and the feed are copies saved from the real services
(`tests/fixtures/podcast/`). Gemini and Claude are played by stand-ins, so no test listens to anything.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import config, db
from backend.ai import gemini
from backend.analyzers import analyzers
from backend.connectors import Context, connectors, podcast
from backend.fetchers import FetchError, FetchResult
from backend.main import app
from backend.pipeline import scrape as scraping
from backend.pipeline import videos
from backend.pipeline.scrape import scrape_source
from backend.schemas import FeedRecipe, Recipe
from tests.test_pipeline import add_source
from tests.test_youtube import ARTICLE, TRANSCRIPT, claude_writes, wait_for

FIXTURES = Path(__file__).parent / "fixtures" / "podcast"
EPISODE = "31voblXKw2y8zqxDl72i3w"
SHOW = "3IM0lmZxpFAY7CwMuv9H4g"
EPISODE_URL = f"https://open.spotify.com/episode/{EPISODE}"
SHOW_URL = f"https://open.spotify.com/show/{SHOW}"
FEED = "https://feeds.simplecast.com/Sl5CSM3S"
TITLE = "When A.I. Comes for Your Purpose in Life"
SECOND = "The Israeli Film Directors Pushing for a Reckoning in Their Home Country"  # the episode of the day before
# A feed that carries the publisher's own transcripts, in the Podcasting 2.0 way. Written for this test.
OWN_FEED = "https://example.org/show.rss"
OWN = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel><title>Strait Talk</title><link>https://example.org/</link><itunes:author>Example Institute</itunes:author>
<description>A show about sea lanes.</description>
<item><guid isPermaLink="false">ep-2</guid><title>Why the strait matters</title><link>https://example.org/episodes/2</link>
<pubDate>Mon, 05 Oct 2026 08:00:00 +0000</pubDate><itunes:duration>12:30</itunes:duration>
<description><![CDATA[<p>On chokepoints.</p><p>With a guest.</p>]]></description>
<enclosure url="https://example.org/audio/2.mp3?source=feed&amp;x=1" type="audio/mpeg" length="9000000"/>
<podcast:transcript url="https://example.org/transcripts/2.html" type="text/html"/>
<podcast:transcript url="https://example.org/transcripts/2.vtt" type="text/vtt"/></item>
<item><guid isPermaLink="false">ep-1</guid><title>The first one</title><link>https://example.org/episodes/1</link>
<pubDate>Mon, 28 Sep 2026 08:00:00 +0000</pubDate><itunes:duration>600</itunes:duration>
<description>Short notes.</description>
<enclosure url="https://example.org/audio/1.mp3" type="audio/mpeg" length="5000000"/></item>
</channel></rss>"""
VTT = "WEBVTT\n\n" + "\n\n".join(
    f"{n}\n00:{n:02d}:00.000 --> 00:{n:02d}:50.000\n<v {'Host' if n % 2 == 0 else 'Guest'}>"
    f"Sentence {n} about the strait, with enough words in it to count as something that was really said aloud."
    for n in range(8))


class Pod(Context):
    """Spotify's two pages, Apple's directory and the show's feed, as they were saved. `only_spotify` makes the
    directory know no such show, which is what a show without a public feed looks like."""

    def __init__(self, only_spotify: bool = False) -> None:
        self.only_spotify = only_spotify
        self.asked: list[str] = []

    def fetch(self, url: str, fetcher: str = "http", **kwargs) -> FetchResult:
        self.asked.append(url)
        if url.startswith("https://itunes.apple.com/search?"):
            found = {"resultCount": 0, "results": []} if self.only_spotify else json.loads(
                (FIXTURES / "itunes_search.json").read_text("utf-8"))
            return FetchResult(url, 200, "application/json", json.dumps(found).encode(), "utf-8")
        saved = {EPISODE_URL: "spotify_episode.html", SHOW_URL: "spotify_show.html", FEED: "feed.xml"}
        if url in saved:
            kind = "application/xml" if url == FEED else "text/html"
            return FetchResult(url, 200, kind, (FIXTURES / saved[url]).read_bytes(), "utf-8")
        own = {OWN_FEED: (OWN, "application/xml"), "https://example.org/transcripts/2.vtt": (VTT, "text/vtt")}
        if url in own:
            return FetchResult(url, 200, own[url][1], own[url][0].encode(), "utf-8")
        raise FetchError(f"HTTP 404 for {url}", status=404)


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def gemini_listens(monkeypatch, answers=None) -> list[dict]:
    """Stand in for the download of an episode's audio and for Gemini hearing it."""
    heard: list[dict] = []

    def fake_fetch(url: str):
        return FetchResult(url, 200, "audio/mpeg", b"ID3" + b"\x00" * 2000)

    def fake_transcribe(content: bytes, content_type: str = "audio/mpeg", name: str = "episode"):
        heard.append({"bytes": len(content), "type": content_type, "name": name})
        answer = (answers or {}).get(name)
        if isinstance(answer, Exception):
            raise answer
        return TRANSCRIPT, {"input_tokens": 64_000, "output_tokens": 900}

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-gemini-test-key-0123456789abcdef")
    monkeypatch.setattr(videos, "fetch_audio", fake_fetch)
    monkeypatch.setattr(gemini, "transcribe_audio", fake_transcribe)
    return heard


def test_spotify_addresses_are_told_apart():
    assert podcast.spotify_ref(f"{EPISODE_URL}?si=abc123") == ("episode", EPISODE)
    assert podcast.spotify_ref(f"https://open.spotify.com/intl-nl/show/{SHOW}") == ("show", SHOW)
    assert podcast.spotify_ref("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT") == ("track", "4cOdK2wGLETKBW3PvgPWqT")
    assert podcast.spotify_ref("https://open.spotify.com/") is None
    assert podcast.spotify_ref(f"https://example.org/episode/{EPISODE}") is None
    assert podcast.is_spotify(EPISODE_URL) and not podcast.is_spotify("https://www.spotify.com/nl/premium/")
    assert [podcast.seconds(length) for length in ("00:33:17", "33:17", "1997", "", "soon")] == [1997, 1997, 1997, 0, 0]


def test_spotify_says_which_episode_and_the_shows_feed_has_it():
    ctx = Pod()
    feed = FeedRecipe(name="Saved", connector="podcast", url=f"{EPISODE_URL}?si=abc", content_type="podcast")
    connector = connectors.get("podcast")
    pages = list(connector.iter_pages(feed, ctx))
    assert len(pages) == 1 and len(pages[0].items) == 1
    item = pages[0].items[0]
    assert (item.url, item.title, item.author) == (EPISODE_URL, TITLE, "The Daily")  # Spotify's page
    assert item.published == "2026-10-13T09:45:00Z" and item.extra["duration"] == "1997"
    assert item.image_url.startswith("https://i.scdn.co/image/")
    assert item.extra["audio_url"].startswith("https://dts.podtrac.com/redirect.mp3/")  # the feed's enclosure
    assert "&amp;" not in item.extra["audio_url"] and item.extra["audio_type"] == "audio/mpeg"
    assert "no_audio" not in item.extra and "transcript_url" not in item.extra
    # one page of Spotify, one question to the directory, one feed: and nothing of Spotify's player
    assert ctx.asked == [EPISODE_URL, "https://itunes.apple.com/search?media=podcast&entity=podcast&limit=25&term=The+Daily",
                         FEED]
    read = connector.read_item(item, feed, ctx)
    assert read.content_type == "podcast" and read.title == TITLE
    assert read.text.startswith("Artificial intelligence has gone from struggling with basic arithmetic")
    assert "\n\nSteven Strogatz, a professor of mathematics" in read.text  # the feed's paragraphs, not Spotify's run-on


def test_an_episode_is_found_when_its_title_was_edited_and_not_when_it_is_not_there():
    listed = podcast.episodes(FEED, Pod())[1]
    assert [episode.title for episode in listed][0] == TITLE and len(listed) == 4
    same_day = podcast.find_episode(listed, "When AI Comes for Your Purpose in Life (Update)", "2026-10-13T10:00:00Z", 2010)
    assert same_day is listed[0]  # by its day and its length
    assert podcast.find_episode(listed, "when a.i. comes for your purpose in life!") is listed[0]
    assert podcast.find_episode(listed, "An episode from 2019", "2019-03-01T00:00:00Z", 1500) is None


def test_an_episode_saved_by_its_spotify_address_is_written_out_and_written_up(api, monkeypatch):
    ctx = Pod()
    monkeypatch.setattr(scraping, "Context", lambda: ctx)
    heard, sent = gemini_listens(monkeypatch), claude_writes(monkeypatch)
    started = api.post("/api/links", json={"url": f"https://open.spotify.com/intl-nl/episode/{EPISODE}?si=xyz"}).json()
    job = wait_for(api, started["job_id"])
    assert job["status"] == "done" and job["result"]["videos"]["written_up"] == 1
    assert heard == [{"bytes": 2003, "type": "audio/mpeg", "name": TITLE}]
    assert any("Downloading the audio" in line["msg"] for line in job["logs"])
    assert any("1 podcast episode written up as an article" in line["msg"] for line in job["logs"])

    episode = api.get(f"/api/articles/{job['result']['article_id']}").json()
    assert episode["url"] == EPISODE_URL and episode["source_name"] == "Saved podcasts"
    assert (episode["content_type"], episode["duration_seconds"], episode["video_id"]) == ("podcast", 1997, "")
    assert episode["audio_url"].startswith("https://dts.podtrac.com/") and episode["author"] == "The Daily"
    assert episode["text"] == ARTICLE and episode["transcript"] == TRANSCRIPT
    assert episode["original_text"].startswith("Artificial intelligence has gone from")  # the description is kept
    request = sent[0]
    assert f"Podcast episode: {TITLE}\nShow: The Daily\nPublished: 2026-10-13" in request["prompt"]
    assert "transcript of a podcast episode" in request["system"] and "video" not in request["system"]
    assert "the episode as an article" in request["prompt"] and "the video" not in request["prompt"]
    kinds = {source["name"]: (source["kind"], source["saved"]) for source in api.get("/api/sources").json()}
    assert kinds == {"Saved podcasts": ("podcasts", "podcast")}
    assert api.post("/api/links", json={"url": EPISODE_URL}).json()["already"] is True

    show = api.post("/api/links", json={"url": SHOW_URL})
    assert show.status_code == 400 and "add it as a source" in show.json()["detail"]
    music = api.post("/api/links", json={"url": "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT"})
    assert music.status_code == 400 and "not a podcast episode" in music.json()["detail"]


def test_a_show_that_is_only_on_spotify_is_stored_with_its_description(api, monkeypatch):
    ctx = Pod(only_spotify=True)
    monkeypatch.setattr(scraping, "Context", lambda: ctx)
    heard = gemini_listens(monkeypatch)
    job = wait_for(api, api.post("/api/links", json={"url": EPISODE_URL}).json()["job_id"])
    assert job["status"] == "done" and heard == []
    assert any("No public feed was found for the show 'The Daily'" in line["msg"] for line in job["logs"])
    episode = api.get(f"/api/articles/{job['result']['article_id']}").json()
    assert episode["title"] == TITLE and episode["audio_url"] == "" and episode["content_type"] == "podcast"
    assert episode["text"].startswith("Artificial intelligence has gone from") and episode["duration_seconds"] == 1997
    waiting = api.get(f"/api/sources/{episode['source_id']}").json()["videos"]
    assert (waiting["videos"], waiting["no_audio"], waiting["to_write_out"]) == (1, 1, 0)


def test_quick_detect_follows_a_show_from_its_feed_a_few_episodes_per_run(api, job, monkeypatch):
    ctx = Pod()
    analysis = analyzers.get("heuristic").analyze(SHOW_URL, "", job, ctx)
    recipe = analysis.recipe
    assert recipe.site_name == "The Daily" and recipe.homepage == SHOW_URL
    assert [(feed.connector, feed.url, feed.content_type) for feed in recipe.feeds] == [("podcast", FEED, "podcast")]
    assert FEED in recipe.structure_report and "4 episodes" in recipe.structure_report

    heard = gemini_listens(monkeypatch)
    claude_writes(monkeypatch)
    config.update({"podcasts_per_run": 2})
    source_id = add_source(recipe)
    totals = scrape_source(source_id, job, ctx=ctx)
    assert totals["new"] == 4 and totals["videos"]["written_out"] == 2 and totals["videos"]["written_up"] == 2
    assert [entry["name"] for entry in heard] == [TITLE, SECOND]  # newest first
    stored = db.rows("SELECT url, content_type, audio_url, written_at FROM articles ORDER BY published_at DESC")
    # every episode of this feed links to the show's site, so each is known by the feed and its own id
    assert stored[0]["url"] == f"{FEED}#5907e0b8-863f-4fa3-bee0-83ead32ae62a" and len({row["url"] for row in stored}) == 4
    assert all(row["content_type"] == "podcast" and row["audio_url"] for row in stored)
    source = api.get(f"/api/sources/{source_id}").json()
    assert source["kind"] == "podcasts" and source["videos"]["per_run"] == 2
    assert (source["videos"]["written"], source["videos"]["to_write_out"]) == (2, 2)

    episode = analyzers.get("heuristic").analyze(EPISODE_URL, "", job, ctx)  # an episode's address leads to its show
    assert episode.recipe.feeds[0].url == FEED


def test_a_feeds_own_transcript_is_used_and_nothing_is_listened_to(job, monkeypatch):
    ctx = Pod()
    heard, sent = gemini_listens(monkeypatch), claude_writes(monkeypatch)
    source_id = add_source(Recipe(site_name="Strait Talk", homepage="https://example.org/", feeds=[
        FeedRecipe(name="Episodes", connector="podcast", url=OWN_FEED, content_type="podcast")]))
    totals = scrape_source(source_id, job, ctx=ctx)
    assert totals["new"] == 2
    assert "https://example.org/transcripts/2.vtt" in ctx.asked  # the kind that reads best, of the two offered
    assert "https://example.org/transcripts/2.html" not in ctx.asked
    second, first = db.rows("SELECT * FROM articles ORDER BY published_at DESC")
    assert second["url"] == "https://example.org/episodes/2" and second["duration_seconds"] == 750
    assert second["audio_url"] == "https://example.org/audio/2.mp3?source=feed&x=1"
    assert second["transcript"].startswith("[00:00] Host: Sentence 0 about the strait")
    assert "\n\n[01:00] Guest: Sentence 1" in second["transcript"] and second["written_at"]
    wrote = next(request for request in sent if "Podcast episode: Why the strait matters" in request["prompt"])
    assert "[00:00] Host: Sentence 0" in wrote["prompt"]  # Claude writes it up from the publisher's words
    assert [entry["name"] for entry in heard] == ["The first one"]  # only the episode without one is listened to
    assert first["transcript"] == TRANSCRIPT and first["duration_seconds"] == 600


def test_transcripts_come_in_several_formats():
    srt = "1\n00:00:01,000 --> 00:00:04,000\nHello and welcome.\n\n2\n00:00:04,000 --> 00:00:09,500\nToday: the strait.\n"
    assert podcast.transcript_text(srt, "application/x-subrip") == "[00:01] Hello and welcome. Today: the strait."
    segments = {"version": "1.0.0", "segments": [
        {"speaker": "Ana", "startTime": 0.5, "body": "Welcome back."}, {"speaker": "Ana", "startTime": 3, "body": "Our guest is here."},
        {"speaker": "Ben", "startTime": 3725, "body": "Thank you."}]}
    assert podcast.transcript_text(json.dumps(segments), "application/json") == (
        "[00:00] Ana: Welcome back. Our guest is here.\n\n[1:02:05] Ben: Thank you.")
    assert podcast.transcript_text("<html><body><p>First.</p><p>Second.</p></body></html>", "text/html") == "First.\n\nSecond."
    assert podcast.transcript_text("First line.\n\nSecond  line.\n", "text/plain") == "First line.\n\nSecond line."
    long_talk = "WEBVTT\n\n" + "\n\n".join(f"00:00:{n:02d}.000 --> 00:00:{n + 1:02d}.000\n{'word ' * 30}" for n in range(0, 40, 2))
    assert long_talk.count("-->") == 20 and podcast.transcript_text(long_talk).count("\n\n") >= 3  # cut into paragraphs


# --- Gemini, as it is handed an audio file over the wire --------------------------------------------

class FilesServer(BaseHTTPRequestHandler):
    seen: list[tuple] = []
    interaction: tuple[int, dict] = (200, {})

    def log_message(self, *args) -> None:
        pass

    def _reply(self, status: int, answer: dict, headers: dict | None = None) -> None:
        data = json.dumps(answer).encode()
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        base = f"http://{self.headers['Host']}"
        if self.path == "/upload/v1beta/files":
            FilesServer.seen.append(("start", self.headers.get("X-Goog-Upload-Header-Content-Type"),
                                     self.headers.get("X-Goog-Upload-Header-Content-Length"), json.loads(body)))
            self._reply(200, {}, {"x-goog-upload-url": f"{base}/upload-session/7"})
        elif self.path == "/upload-session/7":
            FilesServer.seen.append(("upload", self.headers.get("X-Goog-Upload-Command"), len(body)))
            self._reply(200, {"file": {"name": "files/abc", "uri": "https://files.example/abc", "state": "PROCESSING"}})
        else:
            FilesServer.seen.append(("ask", self.path, self.headers.get("x-goog-api-key"), json.loads(body)))
            self._reply(*FilesServer.interaction)

    def do_GET(self) -> None:
        FilesServer.seen.append(("state", self.path))
        self._reply(200, {"name": "files/abc", "uri": "https://files.example/abc", "state": "ACTIVE"})

    def do_DELETE(self) -> None:
        FilesServer.seen.append(("delete", self.path))
        self._reply(200, {})


@pytest.fixture
def files_server(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), FilesServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FilesServer.seen.clear()
    monkeypatch.setenv("GEMINI_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v1beta")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-gemini-test-key-0123456789abcdef")
    monkeypatch.setattr(gemini.time, "sleep", lambda seconds: None)
    yield FilesServer
    server.shutdown()


def test_gemini_is_handed_the_audio_file_and_the_file_is_deleted_again(files_server):
    files_server.interaction = (200, {"status": "completed", "steps": [
        {"type": "model_output", "content": [{"type": "text", "text": "[00:00] Host: Welcome."}]}],
        "usage": {"total_input_tokens": 64_000, "total_output_tokens": 30}})
    text, used = gemini.transcribe_audio(b"ID3" + b"\x00" * 500, "audio/mpeg", "An episode")
    assert text == "[00:00] Host: Welcome." and used == {"input_tokens": 64_000, "output_tokens": 30}
    steps = [entry[0] for entry in files_server.seen]
    assert steps == ["start", "upload", "state", "ask", "delete"]
    assert files_server.seen[0][1:] == ("audio/mp3", "503", {"file": {"display_name": "An episode"}})
    assert files_server.seen[1][1:] == ("upload, finalize", 503)
    asked = files_server.seen[3]
    assert asked[1] == "/v1beta/interactions" and asked[2].startswith("AIzaSy-gemini")
    assert asked[3]["input"][1] == {"type": "audio", "uri": "https://files.example/abc", "mime_type": "audio/mp3"}
    assert "recording" in asked[3]["input"][0]["text"] and "[MM:SS]" in asked[3]["input"][0]["text"]
    assert asked[3]["store"] is False and files_server.seen[4] == ("delete", "/v1beta/files/abc")

    files_server.seen.clear()
    files_server.interaction = (429, {"error": {"message": "Quota exceeded"}})
    with pytest.raises(gemini.TryLater, match="Quota exceeded"):
        gemini.transcribe_audio(b"ID3", "audio/mpeg")
    assert files_server.seen[-1] == ("delete", "/v1beta/files/abc")  # also when Gemini could not hear it
    files_server.interaction = (400, {"error": {"message": "Unsupported audio"}})
    with pytest.raises(gemini.GeminiError, match="could not read this recording \\(HTTP 400: Unsupported audio\\)"):
        gemini.transcribe_audio(b"ID3", "audio/x-m4a")
    assert [entry for entry in files_server.seen if entry[0] == "start"][-1][1] == "audio/m4a"


def test_audio_that_cannot_be_fetched_or_heard_costs_that_episode_only(job, monkeypatch):
    ctx = Pod()
    claude_writes(monkeypatch)
    heard = gemini_listens(monkeypatch, {SECOND: gemini.GeminiError("Gemini returned no text for this recording.")})
    fetched: list[str] = []

    def fetch(url: str):
        fetched.append(url)
        if len(fetched) == 1:
            raise FetchError("HTTP 403 for the audio", status=403, refused=True)
        return FetchResult(url, 200, "audio/mpeg", b"ID3")

    monkeypatch.setattr(videos, "fetch_audio", fetch)
    config.update({"podcasts_per_run": 3})
    source_id = add_source(Recipe(site_name="The Daily", homepage=SHOW_URL, feeds=[
        FeedRecipe(name="Episodes", connector="podcast", url=FEED, content_type="podcast")]))
    totals = scrape_source(source_id, job, ctx=ctx)
    assert totals["videos"] == {"written_out": 1, "failed": 2, "waiting": 0, "written_up": 1, "over_budget": 0}
    assert len(fetched) == 3 and len(heard) == 2
    assert "HTTP 403 for the audio" in job.text() and "returned no text" in job.text()
    waiting = videos.waiting(source_id)
    assert (waiting["failed"], waiting["to_write_out"], waiting["written"]) == (2, 1, 1)


# --- the two buttons: everything that is left, and one episode ------------------------------------------

def followed_show(job, monkeypatch, **settings) -> int:
    """The Daily, followed: four episodes stored, of which a first run has done as many as `podcasts_per_run`."""
    config.update({"podcasts_per_run": 1, **settings})
    source_id = add_source(Recipe(site_name="The Daily", homepage=SHOW_URL, feeds=[
        FeedRecipe(name="Episodes", connector="podcast", url=FEED, content_type="podcast")]))
    scrape_source(source_id, job, ctx=Pod())
    return source_id


def test_everything_that_is_left_is_done_when_asked_for(api, job, monkeypatch):
    heard = gemini_listens(monkeypatch)
    claude_writes(monkeypatch)
    source_id = followed_show(job, monkeypatch)
    assert len(heard) == 1  # a run by itself does one

    waiting = api.get(f"/api/sources/{source_id}").json()["videos"]
    assert (waiting["written"], waiting["to_write_out"], waiting["all"], waiting["can_write_one"]) == (1, 3, 3, True)
    assert 4 <= waiting["all_minutes"] <= 12 and 0 < waiting["all_usd"] < 0.05  # three episodes of 30 to 40 minutes

    started = api.post(f"/api/sources/{source_id}/videos", json={"everything": True}).json()
    done = wait_for(api, started["job_id"])
    assert done["status"] == "done" and done["title"] == "Transcribe and summarise: The Daily"
    assert done["result"]["written_out"] == 3 and done["result"]["written_up"] == 3 and len(heard) == 4
    after = api.get(f"/api/sources/{source_id}").json()["videos"]
    assert (after["written"], after["all"], after["all_minutes"], after["all_usd"]) == (4, 0, 0, 0)

    without = api.post(f"/api/sources/{source_id}/videos", json={}).json()  # nothing left: a run that does nothing
    assert wait_for(api, without["job_id"])["result"] == {}


def test_one_episode_is_written_out_and_written_up_from_the_reader(api, job, monkeypatch):
    heard = gemini_listens(monkeypatch)
    sent = claude_writes(monkeypatch)
    source_id = followed_show(job, monkeypatch, video_max_minutes=1)  # every episode is "too long" for a run
    assert heard == [] and videos.waiting(source_id)["too_long"] == 4
    episodes = db.rows("SELECT id, title FROM articles ORDER BY published_at DESC")
    third = episodes[2]

    done = wait_for(api, api.post(f"/api/articles/{third['id']}/write").json()["job_id"])
    assert done["status"] == "done" and done["result"]["written_out"] == 1 and done["result"]["written_up"] == 1
    assert done["title"].startswith("Transcribe and summarise: Celine Dion") and done["source_id"] == source_id
    assert [entry["name"] for entry in heard] == [third["title"]]  # this one, long as it is, and no other
    written = api.get(f"/api/articles/{third['id']}").json()
    assert written["text"] == ARTICLE and written["transcript"] == TRANSCRIPT and written["written_at"]
    assert db.scalar("SELECT COUNT(*) FROM articles WHERE written_at != ''") == 1 and len(sent) == 1
    assert done["usage"]["calls"] == 1

    assert api.post(f"/api/articles/{third['id']}/write").status_code == 409  # done already
    assert api.post("/api/articles/99999/write").status_code == 404


def test_what_one_episode_runs_into_is_said_on_its_job(api, job, monkeypatch):
    claude_writes(monkeypatch)
    answers: dict = {TITLE: gemini.TryLater("Gemini cannot take more right now (HTTP 429: quota)."),
                     SECOND: gemini.GeminiError("Gemini returned no text for this recording.")}
    heard = gemini_listens(monkeypatch, answers)
    source_id = followed_show(job, monkeypatch, podcasts_per_run=0)
    first, second, third, _ = db.rows("SELECT id, title FROM articles ORDER BY published_at DESC")

    later = wait_for(api, api.post(f"/api/articles/{first['id']}/write").json()["job_id"])
    assert later["status"] == "error" and "cannot take more right now" in later["error"]
    assert db.scalar("SELECT transcribed_at FROM articles WHERE id = ?", (first["id"],)) == ""  # not held against it

    failed = wait_for(api, api.post(f"/api/articles/{second['id']}/write").json()["job_id"])
    assert failed["status"] == "error" and "No transcript: Gemini returned no text" in failed["error"]
    assert videos.waiting(source_id)["failed"] == 1
    answers.pop(SECOND)  # the button tries again what failed before
    again = wait_for(api, api.post(f"/api/articles/{second['id']}/write").json()["job_id"])
    assert again["status"] == "done" and videos.waiting(source_id)["failed"] == 0

    db.execute("UPDATE articles SET audio_url = '' WHERE id = ?", (third["id"],))  # as of a show only on Spotify
    silent = wait_for(api, api.post(f"/api/articles/{third['id']}/write").json()["job_id"])
    assert silent["status"] == "error" and "no audio to be had" in silent["error"]
    assert [entry["name"] for entry in heard] == [TITLE, SECOND, SECOND]

    page = db.execute("INSERT INTO articles(source_id, url, title, fetched_at) VALUES(?, 'https://example.org/a', 'A page', ?)",
                      (source_id, db.now())).lastrowid
    assert api.post(f"/api/articles/{page}/write").status_code == 404  # an article is not a recording
