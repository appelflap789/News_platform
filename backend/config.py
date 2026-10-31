"""Configuration.

Two layers:
* process settings come from `.env` (API key, host, port, data folder);
* user settings are edited on the Settings page and stored in the database.
  `SETTINGS` below is the single list of them: add an entry here and it shows
  up on the Settings page and is readable with `config.get("key")`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
load_dotenv(ENV_FILE)

DATA_DIR = Path(os.environ.get("NSP_DATA_DIR") or ROOT / "data")
DB_PATH = DATA_DIR / "platform.db"
MODELS_DIR = Path(os.environ.get("NSP_MODELS_DIR") or DATA_DIR / "models")  # the downloaded embedding model
FRONTEND_DIST = ROOT / "frontend" / "dist"
HOST = os.environ.get("NSP_HOST", "127.0.0.1")
PORT = int(os.environ.get("NSP_PORT", "8765"))

MODEL_CHOICES = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
EFFORT_CHOICES = ["low", "medium", "high", "xhigh", "max"]
ARTICLE_LANGUAGE = "Same as the article"
SUMMARY_LANGUAGES = ["English", "Dutch", "German", "French", ARTICLE_LANGUAGE]

SETTINGS: list[dict] = [
    {
        "key": "model_analyzer", "group": "Claude", "type": "select", "choices": MODEL_CHOICES,
        "default": "claude-opus-5-5", "label": "Source analysis model",
        "help": "Studies a new source and writes its recipe. Runs once per source.",
    },
    {
        "key": "analyzer_effort", "group": "Claude", "type": "select", "choices": EFFORT_CHOICES,
        "default": "high", "label": "Source analysis effort",
        "help": "How thoroughly Claude investigates a site. Higher is slower and costs more.",
    },
    {
        "key": "model_topics", "group": "Claude", "type": "select", "choices": MODEL_CHOICES,
        "default": "claude-opus-5-5", "label": "Topic model",
        "help": "Expands a topic into search terms and writes 'The long run' on a topic page. One long run reads "
                "about thirty items, so it is the most expensive single request the platform makes; the button "
                "shows the price first.",
    },
    {
        "key": "model_topic_news", "group": "Claude", "type": "select", "choices": MODEL_CHOICES,
        "default": "claude-haiku-5-5", "label": "Topic update model",
        "help": "Writes 'What is new' on a topic page from the items that arrived since the last update. A short "
                "request: a fraction of a cent with Claude Haiku, 20 times that with Claude Sonnet, 40 times "
                "with Claude Opus.",
    },
    {
        "key": "model_enrich", "group": "Claude", "type": "select", "choices": MODEL_CHOICES,
        "default": "claude-haiku-5-5", "label": "Article tagging model",
        "help": "Only used for sources where 'AI summary + tags' is switched on. Runs once per article.",
    },
    {
        "key": "summary_language", "group": "Claude", "type": "select", "choices": SUMMARY_LANGUAGES,
        "default": "English", "label": "AI summary language",
        "help": "The language article summaries are written in, whatever language the article is in. "
                "Tags are always English.",
    },
    {
        "key": "model_translate", "group": "Claude", "type": "select", "choices": MODEL_CHOICES,
        "default": "claude-haiku-5-5", "label": "Translation model",
        "help": "Used by the Translate buttons, on a source's page and in the reader. Runs once per item that "
                "is not in English; a long text is several requests. Claude Haiku is the cheapest: the same text "
                "costs 20 times as much with Claude Sonnet, 40 times with Claude Opus and 100 times with "
                "Claude Fable.",
    },
    {
        "key": "translate_max_minutes", "group": "Claude", "type": "number", "default": 20,
        "label": "Longest item the Translate button on a source's page does (minutes of reading)",
        "help": "Items in another language that take longer to read are left out of it, as the page says; the "
                "Translate button in the reader still translates one of them. Counted as the cards count a "
                "'min read'. 0 = no limit.",
    },
    {
        "key": "model_videos", "group": "Claude", "type": "select", "choices": MODEL_CHOICES,
        "default": "claude-haiku-5-5", "label": "Video and podcast article model",
        "help": "Turns the transcript of a video or a podcast episode into a structured article with a summary "
                "and tags. Runs once per video or episode that has a transcript. With Claude Haiku twenty "
                "minutes of talking costs about a fifth of a cent; Claude Sonnet costs 20 times as much and "
                "Claude Opus 40 times.",
    },
    {
        "key": "claude_budget_usd", "group": "Claude", "type": "number", "default": 0.5,
        "label": "Most one run may spend on translating and summarising (USD)",
        "help": "A scrape, or a run of the label button, skips an item when it would take the run past this "
                "amount. What is skipped stays as it is and can be done in a later run. Topic pages that update "
                "themselves after a scrape count towards the same amount. The Translate button says what it "
                "costs before it starts and may spend that, a quarter more at most, also when it is more "
                "than this. 0 = no limit.",
    },
    {
        "key": "refusal_fallback", "group": "Claude", "type": "bool", "default": True,
        "label": "Retry declined requests on a fallback model",
        "help": "If a safety classifier declines a request, Anthropic re-runs it on its recommended fallback model.",
    },
    {
        "key": "briefing_max_articles", "group": "Claude", "type": "number", "default": 30,
        "label": "Items read for 'The long run'",
        "help": "How many of a topic's best-matching items its long-run summary is written from.",
    },
    {
        "key": "meaning_enabled", "group": "Search by meaning", "type": "bool", "default": True,
        "label": "Understand items by meaning",
        "help": "Gives every item an embedding: a list of numbers that stands for what it is about. A free model "
                "on this computer makes them (one download of about 240 MB, then no internet needed); nothing "
                "is sent anywhere and it costs nothing. Search, topics and 'More like this' use them.",
    },
    {
        "key": "gemini_model", "group": "Videos", "type": "text", "default": "gemini-3.8-flash",
        "label": "Gemini model that reads videos and podcasts",
        "help": "YouTube's own API does not give out the transcript of someone else's video, and Spotify gives "
                "out none at all. Google's Gemini API can read a public video, or the audio file of a podcast "
                "episode, and write out what is said; this is the model asked to do that. It needs a Gemini API "
                "key (above).",
    },
    {
        "key": "video_max_minutes", "group": "Videos", "type": "number", "default": 120,
        "label": "Longest video or episode to transcribe (minutes)",
        "help": "Longer videos and podcast episodes are stored with their description only. 0 = no limit. "
                "Google's free tier reads at most eight hours of video a day.",
    },
    {
        "key": "videos_per_run", "group": "Videos", "type": "number", "default": 25,
        "label": "Videos transcribed in one run",
        "help": "A scrape, or a press of the button on a source's Settings tab, transcribes at most this many "
                "videos, the newest first; the rest wait for a later run. A whole channel is done in steps.",
    },
    {
        "key": "podcasts_per_run", "group": "Videos", "type": "number", "default": 5,
        "label": "Podcast episodes transcribed in one run",
        "help": "The same for podcast episodes. Fewer than videos, because an episode's audio file (often 50 MB "
                "or more) is downloaded and handed to Gemini, and an hour of talking takes it a few minutes.",
    },
    {
        "key": "user_agent", "group": "Scraping", "type": "text",
        "default": "NewsScraperPlatform/1.0 (personal research dashboard)", "label": "User agent",
        "help": "How the scraper identifies itself to websites.",
    },
    {
        "key": "request_delay_seconds", "group": "Scraping", "type": "number", "default": 1.0,
        "label": "Delay between requests to one site (seconds)",
        "help": "Politeness delay. Lower is faster but more likely to get you blocked.",
    },
    {
        "key": "respect_robots", "group": "Scraping", "type": "bool", "default": True,
        "label": "Respect robots.txt",
        "help": "Skip pages a site asks crawlers not to visit.",
    },
    {
        "key": "block_private_hosts", "group": "Scraping", "type": "bool", "default": True,
        "label": "Block local network addresses",
        "help": "Refuse to fetch localhost and private network addresses. Keep this on.",
    },
    {
        "key": "max_pages_first", "group": "Scraping", "type": "number", "default": 3,
        "label": "Listing pages on the first scrape",
        "help": "How many pages of a listing to walk the first time a source is scraped.",
    },
    {
        "key": "max_pages_update", "group": "Scraping", "type": "number", "default": 2,
        "label": "Listing pages on an update",
        "help": "Updates stop early as soon as a page has nothing new.",
    },
    {
        "key": "max_pages_deep", "group": "Scraping", "type": "number", "default": 25,
        "label": "Listing pages on a deep scrape",
        "help": "Deep scrape walks the archive, even through pages that are already known.",
    },
    {
        "key": "max_download_mb", "group": "Scraping", "type": "number", "default": 40,
        "label": "Largest download (MB)",
        "help": "Bigger pages and PDFs are skipped.",
    },
]

def model_label(model: str) -> str:
    """'claude-sonnet-5-5' -> 'Claude Sonnet 5.5'"""
    family, *version = model.removeprefix("claude-").split("-")
    return f"Claude {family.title()} {'.'.join(version)}".strip()


_SPEC = {s["key"]: s for s in SETTINGS}
_overrides: dict[str, object] | None = None


def _load() -> dict[str, object]:
    global _overrides
    if _overrides is None:
        from . import db

        _overrides = {r["key"]: json.loads(r["value"]) for r in db.rows("SELECT key, value FROM settings")}
    return _overrides


def get(key: str):
    """Current value of a user setting."""
    spec = _SPEC[key]
    return _load().get(key, spec["default"])


def all_values() -> dict[str, object]:
    return {s["key"]: get(s["key"]) for s in SETTINGS}


def update(values: dict[str, object]) -> None:
    from . import db

    for key, value in values.items():
        spec = _SPEC.get(key)
        if spec is None:
            raise ValueError(f"Unknown setting: {key}")
        value = _coerce(spec, value)
        db.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        _load()[key] = value


def _coerce(spec: dict, value):
    kind = spec["type"]
    if kind == "bool":
        return bool(value)
    if kind == "number":
        number = float(value)
        if number < 0:
            raise ValueError(f"{spec['label']} cannot be negative")
        return int(number) if isinstance(spec["default"], int) else number
    value = str(value).strip()
    if kind == "select" and value not in spec["choices"]:
        raise ValueError(f"{spec['label']}: '{value}' is not one of {spec['choices']}")
    if not value:
        raise ValueError(f"{spec['label']} cannot be empty")
    return value


def reset_cache() -> None:
    global _overrides
    _overrides = None


# --- API keys ----------------------------------------------------------------

# The keys of the two Google services videos use, by the name the dashboard knows them under.
OTHER_KEYS = {"youtube": "YOUTUBE_API_KEY", "gemini": "GEMINI_API_KEY"}


def api_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def other_key(name: str) -> str:
    """The YouTube Data API key ('youtube') or the Gemini API key ('gemini'), or '' when it is not set."""
    return os.environ.get(OTHER_KEYS[name], "").strip()


def save_other_key(name: str, key: str) -> None:
    key = key.strip()
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), OTHER_KEYS[name], key)
    os.environ[OTHER_KEYS[name]] = key


def save_api_key(key: str) -> None:
    """Store the key in `.env` (git-ignored) and make it active immediately."""
    key = key.strip()
    ENV_FILE.touch(exist_ok=True)
    set_key(str(ENV_FILE), "ANTHROPIC_API_KEY", key)
    os.environ["ANTHROPIC_API_KEY"] = key
