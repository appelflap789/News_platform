"""YouTube channels and videos, saving one page or video by its address, and turning a video into an article.

No test reaches YouTube, Google or Claude: the channel feed and the video page are small copies saved from the
real site (tests/fixtures/youtube), the YouTube Data API is played by `Tube`, Gemini by a server in this file.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from backend import config, db
from backend.ai import client as ai
from backend.ai import gemini
from backend.analyzers import analyzers
from backend.connectors import Context, ConnectorError, connectors, youtube
from backend.fetchers import FetchError, FetchResult
from backend.main import app
from backend.pipeline import scrape as scraping
from backend.pipeline import videos
from backend.pipeline.scrape import save_link, scrape_source
from backend.schemas import FeedRecipe, Recipe
from backend.util import word_count
from tests.test_pipeline import add_source

FIXTURES = Path(__file__).parent / "fixtures" / "youtube"
CHANNEL = "UCwnKziETDbHJtx78nIkfYug"
CHANNEL_URL = f"https://www.youtube.com/channel/{CHANNEL}"
VIDEO = "K-qll_Yhfms"  # the video the saved page is of
KEY = "AIzaSy-test-key-0123456789abcdefghijklm"
UPLOADS = {f"vid{n:08d}": n for n in range(1, 6)}  # five videos, vid00000005 the newest


def video_entry(found_id: str, number: int, **snippet) -> dict:
    return {
        "id": found_id,
        "snippet": {"publishedAt": f"2026-10-{number:02d}T10:00:00Z", "channelId": CHANNEL, "channelTitle": "CaspianReport",
                    "title": f"Video number {number} about the strait", "description": f"What video {number} is about.\nSecond line.",
                    "thumbnails": {"high": {"url": f"https://i.ytimg.com/vi/{found_id}/hq.jpg"}}, "tags": ["Geopolitics"],
                    "liveBroadcastContent": "none", **snippet},
        "contentDetails": {"duration": f"PT{number}M30S"},
        "statistics": {"viewCount": str(number * 1000)},
    }


class Tube(Context):
    """YouTube as the platform sees it: the Data API (when a key is set), the channel feed and the video page."""

    def __init__(self) -> None:
        self.asked: list[str] = []
        self.refuse_api = 0  # an HTTP status the API answers everything with
        self.views_times = 1
        self.videos_tab = True  # whether the channel has the playlist and the feed of its Videos tab
        self.channel_feed = "feed.xml"

    def fetch(self, url: str, fetcher: str = "http", **kwargs) -> FetchResult:
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        self.asked.append(parts.path.rsplit("/", 1)[-1] + ("?" + "&".join(f"{k}={v}" for k, v in sorted(query.items()) if k != "key") if query else ""))
        if parts.hostname == "www.googleapis.com":
            assert query.pop("key") == KEY and kwargs.get("robots") is False
            if self.refuse_api:
                raise FetchError(f"HTTP {self.refuse_api} for {url}", refused=True, status=self.refuse_api)
            return FetchResult(url, 200, "application/json", json.dumps(self.api(parts.path, query)).encode(), "utf-8")
        if parts.path == "/feeds/videos.xml" and (query.get("channel_id") == CHANNEL or (
                self.videos_tab and query.get("playlist_id") == "UULF" + CHANNEL[2:])):
            assert kwargs.get("robots") is False  # a feed you subscribed to
            name = self.channel_feed if "channel_id" in query else "feed.xml"
            return FetchResult(url, 200, "text/xml", (FIXTURES / name).read_bytes(), "utf-8")
        if parts.path == "/watch" and query.get("v", "").startswith(("K-qll", "748WJ", "LOOH2", "qcGtW", "zlSpd",
                                                                      "bPSeu", "4ZfTO")):
            return FetchResult(url, 200, "text/html", (FIXTURES / "watch.html").read_bytes(), "utf-8")
        raise FetchError(f"HTTP 404 for {url}", status=404)

    def api(self, path: str, query: dict) -> dict:
        if path.endswith("/channels"):
            if query.get("forHandle") == "@CaspianReport" or query.get("id") == CHANNEL:
                return {"items": [{"id": CHANNEL, "snippet": {"title": "CaspianReport", "description": "Geopolitics explained.",
                                                               "thumbnails": {"default": {"url": "https://yt3.example/c.jpg"}}},
                                   "contentDetails": {"relatedPlaylists": {"uploads": "UU" + CHANNEL[2:]}},
                                   "statistics": {"videoCount": "5"}}]}
            return {"items": []}
        if path.endswith("/playlistItems"):
            assert query["playlistId"] in ("UULF" + CHANNEL[2:], "UU" + CHANNEL[2:]) and query["maxResults"] == "50"
            if query["playlistId"].startswith("UULF") and not self.videos_tab:
                raise FetchError("HTTP 404 for the playlist", status=404)
            newest_first = sorted(UPLOADS, reverse=True)
            start = int(query.get("pageToken", 0))
            page = newest_first[start:start + 2]  # two to a page, to have pages to walk
            answer = {"items": [{"contentDetails": {"videoId": found_id}} for found_id in page], "pageInfo": {"totalResults": 5}}
            if start + 2 < len(newest_first):
                answer["nextPageToken"] = str(start + 2)
            return answer
        if path.endswith("/videos"):
            entries = []
            for found_id in query["id"].split(","):
                if found_id == "vid00000002":
                    continue  # deleted since it was listed
                if found_id in UPLOADS:
                    number = UPLOADS[found_id]
                    entry = video_entry(found_id, number, **({"liveBroadcastContent": "upcoming"} if number == 4 else {}))
                    entry["statistics"]["viewCount"] = str(number * 1000 * self.views_times)
                    entries.append(entry)
                elif found_id == VIDEO:
                    entries.append(video_entry(VIDEO, 5, title="The hidden geography of AI"))
            return {"items": entries}
        raise AssertionError(path)


@pytest.fixture
def tube() -> Tube:
    return Tube()


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", KEY)


@pytest.fixture
def api():
    with TestClient(app) as client:
        yield client


def channel_source(url: str = CHANNEL_URL, **columns) -> int:
    return add_source(Recipe(site_name="CaspianReport", homepage=url, feeds=[
        FeedRecipe(name="Videos", connector="youtube", url=url, content_type="video")]), **columns)


def stored(where: str = "1 = 1") -> list[dict]:
    return db.rows(f"SELECT * FROM articles WHERE {where} ORDER BY published_at DESC")


def wait_for(api: TestClient, job_id: str) -> dict:
    deadline = time.time() + 30
    while time.time() < deadline:
        job = api.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


# --- addresses and the video page ------------------------------------------------------------

def test_addresses_of_videos_and_channels_are_told_apart():
    for url in (f"https://www.youtube.com/watch?v={VIDEO}&t=42s", f"https://youtu.be/{VIDEO}?si=abc",
                f"https://www.youtube.com/shorts/{VIDEO}", f"https://m.youtube.com/live/{VIDEO}",
                f"https://www.youtube-nocookie.com/embed/{VIDEO}"):
        assert youtube.video_id(url) == VIDEO and youtube.channel_ref(url) is None, url
    assert youtube.video_id("https://www.youtube.com/watch?v=short") == ""
    assert youtube.video_id("https://example.org/watch?v=" + VIDEO) == ""
    assert youtube.channel_ref("https://www.youtube.com/@CaspianReport/videos") == ("handle", "@CaspianReport")
    assert youtube.channel_ref(CHANNEL_URL) == ("id", CHANNEL)
    assert youtube.channel_ref("https://www.youtube.com/user/caspianreport") == ("user", "caspianreport")
    assert youtube.channel_ref("https://www.youtube.com/c/CaspianReport") == ("custom", "CaspianReport")
    assert youtube.channel_ref("https://www.youtube.com/") is None and youtube.channel_ref("https://example.org/@x") is None
    assert [youtube.seconds(text) for text in ("PT14M49S", "PT1H2M3S", "PT45S", "P1DT1H", "", "soon")] == [
        889, 3723, 45, 90000, 0, 0]


def test_a_video_page_gives_date_length_views_and_channel():
    page = youtube.parse_watch((FIXTURES / "watch.html").read_text(encoding="utf-8"))
    assert page["title"] == "The hidden geography of AI" and page["published"] == "2026-10-05T08:52:00Z"
    assert page["duration"] == 888 and page["views"] > 200_000 and page["live"] is False
    assert (page["channel"], page["channel_id"]) == ("CaspianReport", CHANNEL)
    assert len(page["description"]) > 500 and page["thumbnail"].endswith("maxresdefault.jpg")
    assert youtube.parse_watch("<html><body>Before you continue to YouTube</body></html>")["title"] == ""


# --- a channel, without and with a YouTube API key -------------------------------------------

def test_without_a_key_a_channel_is_read_from_its_feed_and_each_video_from_its_page(tube, job):
    totals = scrape_source(channel_source(), job, ctx=tube)
    assert totals["new"] == 3 and totals["failed"] == 0
    newest = stored()[0]
    assert newest["url"] == f"https://www.youtube.com/watch?v={VIDEO}" and newest["video_id"] == VIDEO
    assert newest["title"] == "The hidden geography of AI" and newest["author"] == "CaspianReport"
    assert newest["published_at"] == "2026-10-05T08:52:00Z" and newest["content_type"] == "video"
    assert newest["duration_seconds"] == 888 and newest["views"] > 200_000  # the length comes from the video's page
    assert newest["image_url"].startswith("https://i") and not newest["is_partial"]
    assert len(newest["text"]) > 500 and "<p>" not in newest["text"]  # its description, until there is a transcript
    assert tube.asked[0] == f"videos.xml?playlist_id=UULF{CHANNEL[2:]}" and len(tube.asked) == 4  # its Videos tab
    assert "description only" in job.text() and "Gemini API key" in job.text()  # what is missing, said once


def test_without_a_key_a_channel_cannot_be_found_by_its_name(tube, job):
    with pytest.raises(ConnectorError, match="Without a YouTube API key"):
        next(connectors.get("youtube").iter_pages(
            FeedRecipe(name="Videos", connector="youtube", url="https://www.youtube.com/@CaspianReport"), tube))
    assert tube.asked == []  # the channel page is not tried: Europe gets a consent page there


def test_with_a_key_every_video_of_a_channel_is_listed_through_the_api(tube, job, with_key):
    config.update({"max_pages_first": 1})
    source_id = channel_source("https://www.youtube.com/@CaspianReport")
    totals = scrape_source(source_id, job, ctx=tube)
    assert totals["new"] == 1  # the first page lists the two newest; one is a premiere that has not been shown yet
    assert tube.asked == ["channels?forHandle=@CaspianReport&part=snippet,contentDetails,statistics",
                          f"playlistItems?maxResults=50&part=contentDetails&playlistId=UULF{CHANNEL[2:]}",
                          "videos?id=vid00000005,vid00000004&part=snippet,contentDetails,statistics"]
    video = stored()[0]
    assert (video["video_id"], video["views"], video["duration_seconds"]) == ("vid00000005", 5000, 330)
    assert video["text"] == "What video 5 is about.\n\nSecond line." and video["tags"] == "Geopolitics"
    assert video["published_at"] == "2026-10-05T10:00:00Z" and video["image_url"].endswith("/hq.jpg")

    tube.views_times = 3
    deep = scrape_source(source_id, job, deep=True, ctx=tube)
    assert deep["new"] == 2 and [v["video_id"] for v in stored()] == ["vid00000005", "vid00000003", "vid00000001"]
    assert deep["feeds"][0]["pages"] == 3  # the whole channel was walked; the deleted video simply is not there
    assert stored()[0]["views"] == 15000  # a video that was stored already has its views brought up to date


def shorts_feed(shorts: str = "") -> FeedRecipe:
    return FeedRecipe(name="Videos", connector="youtube", url=CHANNEL_URL, content_type="video",
                      options={"shorts": shorts})


def test_shorts_are_left_out_unless_the_feed_says_otherwise(tube, job):
    tube.channel_feed = "feed_with_shorts.xml"  # as YouTube serves it: two videos and two Shorts
    connector = connectors.get("youtube")
    listed = lambda feed: [(item.extra["video_id"], "short" in item.extra)  # noqa: E731
                           for item in next(connector.iter_pages(feed, tube)).items]

    assert len(listed(shorts_feed())) == 3 and tube.asked == [f"videos.xml?playlist_id=UULF{CHANNEL[2:]}"]
    assert listed(shorts_feed("yes")) == [("qcGtWW8uERI", False), ("zlSpdzQhAkE", True), ("bPSeumz6sgI", False),
                                          ("4ZfTOy5OS10", True)]
    assert tube.asked[-1] == f"videos.xml?channel_id={CHANNEL}"  # everything the channel uploaded

    # A channel whose Videos tab has no feed: its own feed says of each entry whether it is a Short.
    tube.videos_tab = False
    assert listed(shorts_feed()) == [("qcGtWW8uERI", False), ("bPSeumz6sgI", False)]
    source_id = add_source(Recipe(site_name="Bloomberg Originals", homepage=CHANNEL_URL, feeds=[shorts_feed()]))
    assert scrape_source(source_id, job, ctx=tube)["new"] == 2
    assert {video["video_id"] for video in stored()} == {"qcGtWW8uERI", "bPSeumz6sgI"}


def test_with_a_key_the_videos_tab_is_listed_and_a_channel_without_one_says_so(tube, job, with_key):
    config.update({"max_pages_first": 1})
    scrape_source(add_source(Recipe(site_name="All of it", homepage=CHANNEL_URL, feeds=[shorts_feed("yes")])),
                  job, ctx=tube)
    assert f"playlistItems?maxResults=50&part=contentDetails&playlistId=UU{CHANNEL[2:]}" in tube.asked

    tube.videos_tab = False
    db.execute("DELETE FROM articles")
    totals = scrape_source(channel_source(), job, ctx=tube)
    assert totals["new"] == 0 and "no regular videos, only Shorts or live streams" in job.text()


def test_a_short_can_still_be_saved_by_its_own_address(tube, job):
    saved = save_link("https://www.youtube.com/watch?v=zlSpdzQhAkE", "video", job, ctx=tube)
    assert saved["new"] == 1 and stored()[0]["video_id"] == "zlSpdzQhAkE"
    assert youtube.video_id("https://www.youtube.com/shorts/zlSpdzQhAkE") == "zlSpdzQhAkE"


def test_a_refused_key_is_explained_and_never_shown(tube, job, with_key):
    tube.refuse_api = 403
    with pytest.raises(Exception) as failure:
        scrape_source(channel_source(), job, ctx=tube)
    assert "YouTube API refused the request (HTTP 403)" in str(failure.value) and "quota" in str(failure.value)
    assert KEY not in str(failure.value) and KEY not in job.text()


def test_quick_detect_makes_a_source_of_a_channel_or_of_the_channel_of_a_video(tube, job, with_key):
    analysis = analyzers.get("heuristic").analyze("https://www.youtube.com/@CaspianReport", "", job, tube)
    recipe = analysis.recipe
    assert (recipe.site_name, recipe.homepage, recipe.icon_url) == ("CaspianReport", CHANNEL_URL, "https://yt3.example/c.jpg")
    feed = recipe.feeds[0]
    assert (feed.connector, feed.url, feed.content_type) == ("youtube", CHANNEL_URL, "video")
    assert "5 videos" in recipe.structure_report and "Gemini" in recipe.structure_report
    assert analysis.previews["Videos"]["items"][0]["title"] == "Video number 5 about the strait"
    assert analyzers.get("claude").analyze(f"https://youtu.be/{VIDEO}", "", job, tube).recipe.homepage == CHANNEL_URL


def test_quick_detect_without_a_key_follows_a_video_to_its_channel(tube, job):
    recipe = analyzers.get("heuristic").analyze(f"https://www.youtube.com/watch?v={VIDEO}", "", job, tube).recipe
    assert (recipe.site_name, recipe.homepage) == ("CaspianReport", CHANNEL_URL)
    with pytest.raises(ConnectorError, match="Without a YouTube API key"):
        analyzers.get("heuristic").analyze("https://www.youtube.com/@CaspianReport", "", job, tube)


# --- from video to article -------------------------------------------------------------------

TRANSCRIPT = ("[00:00] The strait is thirty kilometres wide at its narrowest point.\n\n"
              "[02:15] A fifth of the world's oil passes through it, which is why its closure matters.")
ARTICLE = "The video argues the strait matters.\n\n## Why the strait matters [02:15]\n\nA fifth of the world's oil passes."


def claude_writes(monkeypatch) -> list[dict]:
    sent: list[dict] = []

    def fake_structured(*, model, usage=None, **request):
        sent.append({**request, "model": model})
        if usage is not None:
            usage.add(model, type("U", (), {"input_tokens": 6000, "output_tokens": 1500})())
        return {"article": ARTICLE, "summary": "A video about the strait. It says the strait matters.",
                "tags": ["Strait of Hormuz", "oil"]}

    monkeypatch.setattr(ai, "available", lambda: True)
    monkeypatch.setattr(ai, "structured", fake_structured)
    return sent


def gemini_hears(monkeypatch, answers=None) -> list[str]:
    """Make Gemini answer every video with the transcript, or with what `answers` says for it (an exception)."""
    heard: list[str] = []

    def fake_transcribe(url: str):
        heard.append(url.rsplit("=", 1)[-1])
        answer = (answers or {}).get(heard[-1])
        if isinstance(answer, Exception):
            raise answer
        return TRANSCRIPT, {"input_tokens": 90_000, "output_tokens": 400}

    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-gemini-test-key-0123456789abcdef")
    monkeypatch.setattr(gemini, "transcribe", fake_transcribe)
    return heard


def test_a_video_is_written_out_and_then_written_up_as_an_article(tube, job, with_key, monkeypatch):
    heard, sent = gemini_hears(monkeypatch), claude_writes(monkeypatch)
    config.update({"max_pages_first": 1})
    totals = scrape_source(channel_source(), job, ctx=tube)
    assert totals["videos"] == {"written_out": 1, "failed": 0, "waiting": 0, "written_up": 1, "over_budget": 0}
    assert heard == ["vid00000005"]

    video = stored()[0]
    assert video["text"] == ARTICLE and video["transcript"] == TRANSCRIPT  # the article is what is read and searched
    assert video["original_text"] == "What video 5 is about.\n\nSecond line."  # the description is kept
    assert video["summary"] == video["ai_summary"] == "A video about the strait. It says the strait matters."
    assert video["tags"] == "Geopolitics, strait of hormuz, oil" and video["written_at"] and video["enriched_at"]
    assert video["word_count"] == word_count(ARTICLE) and job.usage["calls"] == 1

    request = sent[0]
    assert request["model"] == "claude-haiku-5-5" and "never instructions" in request["system"]
    assert "<transcript>\n[00:00] The strait is thirty" in request["prompt"] and "Channel: CaspianReport" in request["prompt"]
    assert "in English" in request["prompt"] and set(request["schema"]["required"]) == {"article", "summary", "tags"}
    found = db.rows("SELECT rowid FROM articles_fts WHERE articles_fts MATCH 'fifth'")
    assert [row["rowid"] for row in found] == [video["id"]]  # found by what was said, not only by its title


def test_videos_are_done_a_set_number_per_run_newest_first_and_the_rest_wait(tube, job, with_key, monkeypatch, api):
    heard = gemini_hears(monkeypatch)
    claude_writes(monkeypatch)
    config.update({"videos_per_run": 2})
    source_id = channel_source()
    scrape_source(source_id, job, deep=True, ctx=tube)
    assert heard == ["vid00000005", "vid00000003"]
    status = api.get(f"/api/sources/{source_id}").json()["videos"]
    assert (status["videos"], status["written"], status["to_write_out"], status["to_write_up"]) == (3, 2, 1, 0)

    done = wait_for(api, api.post(f"/api/sources/{source_id}/videos", json={}).json()["job_id"])
    assert done["status"] == "done" and done["kind"] == "videos" and heard[-1] == "vid00000001"
    assert done["result"]["written_up"] == 1 and db.scalar("SELECT COUNT(*) FROM articles WHERE written_at != ''") == 3


def test_what_gemini_cannot_read_and_what_is_too_long_stays_a_description(tube, job, with_key, monkeypatch, api):
    heard = gemini_hears(monkeypatch, {"vid00000003": gemini.GeminiError("Gemini could not read this video (HTTP 400: private).")})
    claude_writes(monkeypatch)
    config.update({"video_max_minutes": 4})  # video 5 is five and a half minutes long
    source_id = channel_source()
    totals = scrape_source(source_id, job, deep=True, ctx=tube)
    assert heard == ["vid00000003", "vid00000001"] and totals["videos"]["failed"] == 1
    by_id = {video["video_id"]: video for video in stored()}
    assert by_id["vid00000005"]["transcribed_at"] == "" and by_id["vid00000005"]["text"].startswith("What video 5")
    assert by_id["vid00000003"]["transcribed_at"] and by_id["vid00000003"]["transcript"] == ""
    status = api.get(f"/api/sources/{source_id}").json()["videos"]
    assert (status["too_long"], status["failed"], status["written"], status["to_write_out"]) == (1, 1, 1, 0)

    # The button can give the failed one another go; a later scrape does not, by itself.
    scrape_source(source_id, job, ctx=tube)
    assert len(heard) == 2
    wait_for(api, api.post(f"/api/sources/{source_id}/videos", json={"retry": True}).json()["job_id"])
    assert heard[-1] == "vid00000003"


def test_each_video_becomes_an_article_as_soon_as_it_is_written_out(tube, job, with_key, monkeypatch):
    order: list[str] = []
    heard = gemini_hears(monkeypatch)
    sent = claude_writes(monkeypatch)
    real_transcribe, real_structured = gemini.transcribe, ai.structured
    monkeypatch.setattr(gemini, "transcribe", lambda url: order.append("out") or real_transcribe(url))
    monkeypatch.setattr(ai, "structured", lambda **request: order.append("up") or real_structured(**request))
    scrape_source(channel_source(), job, deep=True, ctx=tube)
    assert order == ["out", "up", "out", "up", "out", "up"] and len(heard) == len(sent) == 3
    assert job.text().count("Written up as an article: ") == 3 and "3 videos written up as articles." in job.text()


def test_when_gemini_says_come_back_later_the_rest_waits(tube, job, with_key, monkeypatch):
    heard = gemini_hears(monkeypatch, {"vid00000003": gemini.TryLater("Gemini cannot take more right now (HTTP 429: quota).")})
    claude_writes(monkeypatch)
    totals = scrape_source(channel_source(), job, deep=True, ctx=tube)
    assert heard == ["vid00000005", "vid00000003"]
    assert totals["videos"]["waiting"] == 2 and totals["videos"]["written_up"] == 1
    assert "2 videos wait for a later run" in job.text()
    assert db.scalar("SELECT COUNT(*) FROM articles WHERE transcribed_at = ''") == 2  # nothing is held against them


def test_writing_up_stays_within_what_a_run_may_cost_and_can_be_switched_off(tube, job, with_key, monkeypatch):
    gemini_hears(monkeypatch)
    sent = claude_writes(monkeypatch)
    config.update({"claude_budget_usd": 0.0000001})
    source_id = channel_source()
    totals = scrape_source(source_id, job, deep=True, ctx=tube)
    assert totals["videos"]["written_up"] == 0 and totals["videos"]["over_budget"] == 3 and not sent
    assert "the most one run may cost" in job.text()
    assert db.scalar("SELECT COUNT(*) FROM articles WHERE transcript != '' AND written_at = ''") == 3

    db.execute("DELETE FROM articles")
    db.execute("UPDATE sources SET write_videos = 0")
    assert "videos" not in scrape_source(source_id, job, deep=True, ctx=tube)
    assert db.scalar("SELECT COUNT(*) FROM articles WHERE transcript != ''") == 0


def test_the_dashboard_is_told_what_a_video_costs(api, monkeypatch):
    prices = api.get("/api/meta").json()["videos"]
    assert prices["model_label"] == "Claude Haiku 5.5" and prices["gemini"] is False and prices["per_run"] == 25
    assert 0.001 < prices["per_video_usd"] < 0.003 < prices["per_hour_usd"] < 0.006
    config.update({"model_videos": "claude-sonnet-5-5"})
    assert videos.prices()["per_video_usd"] == pytest.approx(20 * prices["per_video_usd"], rel=0.05)


# --- Gemini, as it is spoken to over the wire ------------------------------------------------

class GeminiServer(BaseHTTPRequestHandler):
    seen: list[dict] = []
    answer: tuple[int, dict] = (200, {})

    def log_message(self, *args) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        GeminiServer.seen.append({"path": self.path, "key": self.headers.get("x-goog-api-key"), "body": body})
        status, answer = GeminiServer.answer
        data = json.dumps(answer).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def gemini_server(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), GeminiServer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    GeminiServer.seen.clear()
    monkeypatch.setenv("GEMINI_BASE_URL", f"http://127.0.0.1:{server.server_address[1]}/v1beta")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy-gemini-test-key-0123456789abcdef")
    yield GeminiServer
    server.shutdown()


def test_gemini_is_given_the_address_of_the_video_and_asked_for_what_is_said(gemini_server):
    gemini_server.answer = (200, {"id": "x", "status": "completed", "steps": [
        {"type": "thought"}, {"type": "model_output", "content": [{"type": "text", "text": "[00:00] Hello."},
                                                                 {"type": "text", "text": "[00:05] Goodbye."}]}],
        "usage": {"total_input_tokens": 88_000, "total_output_tokens": 120}})
    text, used = gemini.transcribe(f"https://www.youtube.com/watch?v={VIDEO}")
    assert text == "[00:00] Hello.\n[00:05] Goodbye." and used == {"input_tokens": 88_000, "output_tokens": 120}
    request = gemini_server.seen[0]
    assert request["path"] == "/v1beta/interactions" and request["key"].startswith("AIzaSy-gemini")
    assert request["body"]["model"] == "gemini-3.8-flash" and request["body"]["store"] is False
    assert request["body"]["input"][1] == {"type": "video", "uri": f"https://www.youtube.com/watch?v={VIDEO}"}
    assert "transcript" in request["body"]["input"][0]["text"] and "[MM:SS]" in request["body"]["input"][0]["text"]


def test_what_gemini_answers_when_it_cannot(gemini_server, monkeypatch):
    video = f"https://www.youtube.com/watch?v={VIDEO}"
    gemini_server.answer = (429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}})
    with pytest.raises(gemini.TryLater, match="Quota exceeded"):
        gemini.transcribe(video)
    gemini_server.answer = (403, {"error": {"message": "API key not valid"}})
    with pytest.raises(gemini.Misconfigured, match="not accepted"):
        gemini.transcribe(video)
    gemini_server.answer = (404, {"error": {"message": "model not found"}})
    with pytest.raises(gemini.Misconfigured, match="does not know the model"):
        gemini.transcribe(video)
    gemini_server.answer = (400, {"error": {"message": "The video is private"}})
    with pytest.raises(gemini.GeminiError, match="The video is private"):
        gemini.transcribe(video)
    gemini_server.answer = (200, {"status": "failed", "errors": [{"message": "too long"}]})
    with pytest.raises(gemini.GeminiError, match="did not finish this video \\(failed: too long\\)"):
        gemini.transcribe(video)
    gemini_server.answer = (200, {"status": "completed", "steps": []})
    with pytest.raises(gemini.GeminiError, match="no text"):
        gemini.transcribe(video)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with pytest.raises(gemini.Misconfigured, match="No Gemini API key"):
        gemini.transcribe(video)


# --- saving one page or one video ------------------------------------------------------------

def test_one_page_is_saved_by_its_address(api, site):
    started = api.post("/api/links", json={"url": f"{site}/publications/p1?utm_source=mail"}).json()
    job = wait_for(api, started["job_id"])
    assert job["status"] == "done" and job["kind"] == "save" and job["result"]["new"] == 1
    article = api.get(f"/api/articles/{job['result']['article_id']}").json()
    assert article["title"] == "Drone swarms and the future of air defence" and article["url"] == f"{site}/publications/p1"
    assert article["source_name"] == "Saved articles" and article["word_count"] > 40 and not article["is_partial"]

    source = api.get(f"/api/sources/{article['source_id']}").json()
    assert (source["saved"], source["kind"], source["article_count"], source["feeds"]) == ("article", "articles", 1, [])
    again = api.post("/api/links", json={"url": f"{site}/publications/p1"}).json()
    assert again == {"job_id": None, "article_id": article["id"], "already": True}
    api.post("/api/links", json={"url": f"{site}/publications/p3"})
    assert len(api.get("/api/sources").json()) == 1  # the same source takes every saved page

    gone = wait_for(api, api.post("/api/links", json={"url": f"{site}/publications/nothing-here"}).json()["job_id"])
    assert gone["status"] == "error" and "could not be saved" in gone["error"] and "404" in gone["error"]
    assert api.post("/api/links", json={"url": "not an address"}).status_code == 400


def test_a_save_that_fails_leaves_no_empty_source_behind(api, site):
    failed = wait_for(api, api.post("/api/links", json={"url": f"{site}/publications/nothing-here"}).json()["job_id"])
    assert failed["status"] == "error" and api.get("/api/sources").json() == []


def test_one_video_is_saved_by_its_address_and_a_channel_is_sent_to_the_wizard(api, tube, monkeypatch):
    monkeypatch.setattr(scraping, "Context", lambda: tube)
    heard, sent = gemini_hears(monkeypatch), claude_writes(monkeypatch)
    started = api.post("/api/links", json={"url": f"https://youtu.be/{VIDEO}?si=abc"}).json()
    job = wait_for(api, started["job_id"])
    assert job["status"] == "done" and job["result"]["videos"]["written_up"] == 1 and heard == [VIDEO]

    video = api.get(f"/api/articles/{job['result']['article_id']}").json()
    assert video["url"] == f"https://www.youtube.com/watch?v={VIDEO}" and video["source_name"] == "Saved videos"
    assert (video["video_id"], video["duration_seconds"], video["content_type"]) == (VIDEO, 888, "video")
    assert video["title"] == "The hidden geography of AI" and video["author"] == "CaspianReport"
    assert video["published_at"] == "2026-10-05T08:52:00Z" and video["views"] > 200_000
    assert video["text"] == ARTICLE and video["transcript"] == TRANSCRIPT and len(video["original_text"]) > 500
    assert "Video: The hidden geography of AI" in sent[0]["prompt"]
    card = api.get("/api/articles").json()["items"][0]
    assert (card["video_id"], card["duration_seconds"]) == (VIDEO, 888) and card["views"] == video["views"]
    kinds = {source["name"]: (source["kind"], source["saved"]) for source in api.get("/api/sources").json()}
    assert kinds == {"Saved videos": ("videos", "video")}

    channel = api.post("/api/links", json={"url": "https://www.youtube.com/@CaspianReport"})
    assert channel.status_code == 400 and "add it as a source" in channel.json()["detail"]


def test_a_channel_added_as_a_source_counts_as_videos(api, tube, with_key, monkeypatch):
    recipe = {"site_name": "CaspianReport", "homepage": CHANNEL_URL, "feeds": [
        {"name": "Videos", "connector": "youtube", "url": CHANNEL_URL, "content_type": "video"}]}
    created = api.post("/api/sources", json={"url": CHANNEL_URL, "recipe": recipe, "scrape_now": False,
                                             "write_videos": False}).json()
    source = api.get(f"/api/sources/{created['id']}").json()
    assert (source["kind"], source["saved"], source["write_videos"]) == ("videos", "", False)
    assert api.patch(f"/api/sources/{created['id']}", json={"write_videos": True}).json()["write_videos"] is True


def test_the_google_keys_are_stored_but_never_returned(api, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    assert api.get("/api/meta").json()["keys"] == {"youtube": {"set": False, "key_hint": ""},
                                                   "gemini": {"set": False, "key_hint": ""}}
    assert api.put("/api/settings/keys/youtube", json={"key": "too short"}).status_code == 400
    assert api.put("/api/settings/keys/openai", json={"key": KEY}).status_code == 404
    status = api.put("/api/settings/keys/youtube", json={"key": KEY}).json()
    assert status["youtube"] == {"set": True, "key_hint": "…jklm"} and status["gemini"]["set"] is False
    assert f"YOUTUBE_API_KEY='{KEY}'" in env_file.read_text() or KEY in env_file.read_text()
    assert KEY not in api.get("/api/meta").text and KEY not in api.get("/api/settings").text
    assert api.put("/api/settings/keys/youtube", json={"key": ""}).json()["youtube"]["set"] is False
    monkeypatch.setenv("YOUTUBE_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")


def test_an_older_library_gets_what_videos_need(api, site):
    source_id = channel_source()
    for column in ("video_id", "views", "duration_seconds", "transcript", "transcribed_at", "written_at", "audio_url"):
        db.execute(f"ALTER TABLE articles DROP COLUMN {column}")
    db.execute("ALTER TABLE sources DROP COLUMN write_videos")
    db.init()
    source = api.get(f"/api/sources/{source_id}").json()
    assert source["write_videos"] is True and source["videos"]["videos"] == 0


def test_a_first_scrape_takes_as_many_as_asked_and_an_update_does_not_fill_in_below_them(api, tube, with_key, monkeypatch):
    monkeypatch.setattr(scraping, "Context", lambda: tube)
    config.update({"max_pages_first": 3, "max_pages_update": 3})
    recipe = {"site_name": "CaspianReport", "homepage": CHANNEL_URL, "feeds": [
        {"name": "Videos", "connector": "youtube", "url": CHANNEL_URL, "content_type": "video"}]}
    created = api.post("/api/sources", json={"url": CHANNEL_URL, "recipe": recipe, "write_videos": False,
                                             "first_limit": 1}).json()
    first = wait_for(api, created["job_id"])
    assert first["title"] == "Scrape (the newest 1): CaspianReport" and first["result"]["new"] == 1
    assert [v["video_id"] for v in stored()] == ["vid00000005"]  # three pages were allowed; one video was asked for
    assert any("a deep scrape goes further back" in line["msg"] for line in first["logs"])

    # A newer video is uploaded. The update stores it and stops at the newest video it has: the older ones
    # that were never collected (vid00000003 on the next page) are left alone.
    monkeypatch.setitem(UPLOADS, "vid00000006", 6)
    update = wait_for(api, api.post(f"/api/sources/{created['id']}/scrape", json={}).json()["job_id"])
    assert update["result"]["new"] == 1 and update["result"]["feeds"][0]["pages"] == 1
    assert [v["video_id"] for v in stored()] == ["vid00000006", "vid00000005"]
    assert not any("vid00000003" in asked for asked in tube.asked[-2:])

    deep = wait_for(api, api.post(f"/api/sources/{created['id']}/scrape", json={"deep": True, "limit": 1}).json()["job_id"])
    assert deep["result"]["new"] == 1 and [v["video_id"] for v in stored()][-1] == "vid00000003"  # going back is deep
