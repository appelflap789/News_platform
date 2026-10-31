"""SQLite storage. One connection per thread; full-text search through FTS5."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    url              TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    language         TEXT NOT NULL DEFAULT '',
    icon_url         TEXT NOT NULL DEFAULT '',
    recipe           TEXT NOT NULL,
    analyzer         TEXT NOT NULL DEFAULT '',
    enrich_enabled   INTEGER NOT NULL DEFAULT 0,
    interval_minutes INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    last_scraped_at  TEXT NOT NULL DEFAULT '',
    last_error       TEXT NOT NULL DEFAULT '',
    skip_walled      INTEGER NOT NULL DEFAULT 0,
    write_videos     INTEGER NOT NULL DEFAULT 1
);

-- Items a source did not store because their own page could not be read (a login, a paywall, a refusal) and
-- the source is set to leave those out. They are remembered so that a scrape does not open them again.
CREATE TABLE IF NOT EXISTS left_out (
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    url       TEXT NOT NULL,
    title     TEXT NOT NULL DEFAULT '',
    reason    TEXT NOT NULL,
    at        TEXT NOT NULL,
    PRIMARY KEY (source_id, url)
);

CREATE TABLE IF NOT EXISTS articles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    feed_name    TEXT NOT NULL DEFAULT '',
    url          TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL DEFAULT '',
    author       TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '',
    fetched_at   TEXT NOT NULL,
    summary      TEXT NOT NULL DEFAULT '',
    text         TEXT NOT NULL DEFAULT '',
    image_url    TEXT NOT NULL DEFAULT '',
    pdf_url      TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'article',
    language     TEXT NOT NULL DEFAULT '',
    tags         TEXT NOT NULL DEFAULT '',
    ai_summary   TEXT NOT NULL DEFAULT '',
    enriched_at  TEXT NOT NULL DEFAULT '',
    word_count   INTEGER NOT NULL DEFAULT 0,
    is_partial   INTEGER NOT NULL DEFAULT 0,
    translated_at    TEXT NOT NULL DEFAULT '',
    translated_from  TEXT NOT NULL DEFAULT '',
    original_title   TEXT NOT NULL DEFAULT '',
    original_summary TEXT NOT NULL DEFAULT '',
    original_text    TEXT NOT NULL DEFAULT '',
    video_id         TEXT NOT NULL DEFAULT '',
    views            INTEGER NOT NULL DEFAULT 0,
    duration_seconds INTEGER NOT NULL DEFAULT 0,
    transcript       TEXT NOT NULL DEFAULT '',
    transcribed_at   TEXT NOT NULL DEFAULT '',
    written_at       TEXT NOT NULL DEFAULT '',
    audio_url        TEXT NOT NULL DEFAULT '',
    comments         TEXT NOT NULL DEFAULT '',
    comments_summary TEXT NOT NULL DEFAULT '',
    comments_at      TEXT NOT NULL DEFAULT '',
    favorite_at      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title, summary, ai_summary, tags, text,
    content='articles', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, title, summary, ai_summary, tags, text)
    VALUES (new.id, new.title, new.summary, new.ai_summary, new.tags, new.text);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, summary, ai_summary, tags, text)
    VALUES ('delete', old.id, old.title, old.summary, old.ai_summary, old.tags, old.text);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, summary, ai_summary, tags, text)
    VALUES ('delete', old.id, old.title, old.summary, old.ai_summary, old.tags, old.text);
    INSERT INTO articles_fts(rowid, title, summary, ai_summary, tags, text)
    VALUES (new.id, new.title, new.summary, new.ai_summary, new.tags, new.text);
END;

-- Items you removed yourself. Their address is remembered, so that no scrape stores them again, and the item
-- is kept as it was (`item`: the stored row as JSON), so that it can be put back. See backend/removed.py.
CREATE TABLE IF NOT EXISTS removed (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT NOT NULL UNIQUE,
    source_id    INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    source_name  TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    content_type TEXT NOT NULL DEFAULT 'article',
    published_at TEXT NOT NULL DEFAULT '',
    removed_at   TEXT NOT NULL,
    item         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_removed_source ON removed(source_id);

CREATE TABLE IF NOT EXISTS topics (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    description      TEXT NOT NULL DEFAULT '',
    required_any     TEXT NOT NULL DEFAULT '[]',
    terms            TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    briefing         TEXT NOT NULL DEFAULT '',
    briefing_sources TEXT NOT NULL DEFAULT '[]',
    briefing_at      TEXT NOT NULL DEFAULT '',
    by_meaning       INTEGER NOT NULL DEFAULT 1,
    reach            TEXT NOT NULL DEFAULT 'balanced',
    auto_update      INTEGER NOT NULL DEFAULT 0,
    visited_at       TEXT NOT NULL DEFAULT '',
    cover_url        TEXT NOT NULL DEFAULT ''
);

-- One embedding per item: what it is about, as numbers. `seq` only grows, so "has anything changed" is one
-- cheap question (see search/embed.py).
CREATE TABLE IF NOT EXISTS embeddings (
    seq        INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE REFERENCES articles(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    vector     BLOB NOT NULL
);
-- An embedding is made from the title and the summary. When those change (a translation, a new AI summary)
-- the old one is dropped, and the item is embedded again at the end of the run.
CREATE TRIGGER IF NOT EXISTS articles_embedding_stale AFTER UPDATE OF title, summary, ai_summary ON articles
WHEN old.title IS NOT new.title OR old.summary IS NOT new.summary OR old.ai_summary IS NOT new.ai_summary BEGIN
    DELETE FROM embeddings WHERE article_id = new.id;
END;

-- What you said about one item on one topic: 'in' = belongs here, 'out' = not this.
CREATE TABLE IF NOT EXISTS topic_items (
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    verdict    TEXT NOT NULL,
    PRIMARY KEY (topic_id, article_id)
);

-- Every "What is new" that was written for a topic. The newest one is shown; the older ones stay as the
-- topic's memory and are read when "The long run" is rewritten.
CREATE TABLE IF NOT EXISTS topic_notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    text       TEXT NOT NULL,
    sources    TEXT NOT NULL DEFAULT '[]',
    items      INTEGER NOT NULL DEFAULT 0,
    from_date  TEXT NOT NULL DEFAULT '',
    to_date    TEXT NOT NULL DEFAULT '',
    through    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_topic_notes_topic ON topic_notes(topic_id, id);

CREATE TABLE IF NOT EXISTS jobs (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    source_id   INTEGER,
    topic_id    INTEGER,
    status      TEXT NOT NULL,
    progress    TEXT NOT NULL DEFAULT '{}',
    logs        TEXT NOT NULL DEFAULT '[]',
    result      TEXT NOT NULL DEFAULT 'null',
    usage       TEXT NOT NULL DEFAULT '{}',
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    started_at  TEXT NOT NULL DEFAULT '',
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
"""

# Columns that were added after databases were already in use. `init` adds the ones a database lacks.
ADDED_COLUMNS = [
    ("articles", "translated_at", "TEXT NOT NULL DEFAULT ''"),  # when it was looked at for translation
    ("articles", "translated_from", "TEXT NOT NULL DEFAULT ''"),  # language code; '' = shown as it was written
    ("articles", "original_title", "TEXT NOT NULL DEFAULT ''"),
    ("articles", "original_summary", "TEXT NOT NULL DEFAULT ''"),
    ("articles", "original_text", "TEXT NOT NULL DEFAULT ''"),
    ("sources", "skip_walled", "INTEGER NOT NULL DEFAULT 0"),  # leave out items behind a login or paywall
    ("sources", "write_videos", "INTEGER NOT NULL DEFAULT 1"),  # transcribe videos and write them up as articles
    ("articles", "video_id", "TEXT NOT NULL DEFAULT ''"),  # the YouTube id, for an item that is a video
    ("articles", "views", "INTEGER NOT NULL DEFAULT 0"),  # as counted when the video was last listed
    ("articles", "duration_seconds", "INTEGER NOT NULL DEFAULT 0"),
    ("articles", "transcript", "TEXT NOT NULL DEFAULT ''"),  # what is said in the video, as it was written out
    ("articles", "transcribed_at", "TEXT NOT NULL DEFAULT ''"),  # when that was tried ('' = not yet)
    ("articles", "written_at", "TEXT NOT NULL DEFAULT ''"),  # when Claude made the article from the transcript
    ("articles", "audio_url", "TEXT NOT NULL DEFAULT ''"),  # a podcast episode: the audio file its feed offers
    ("articles", "comments", "TEXT NOT NULL DEFAULT ''"),  # an item from Reddit: the comments under its post, as read
    ("articles", "comments_summary", "TEXT NOT NULL DEFAULT ''"),  # ... what they say, summed up by Claude
    ("articles", "comments_at", "TEXT NOT NULL DEFAULT ''"),  # ... and when (pipeline/comments.py)
    ("articles", "favorite_at", "TEXT NOT NULL DEFAULT ''"),  # when you starred it ('' = not a favorite)
    ("topics", "by_meaning", "INTEGER NOT NULL DEFAULT 1"),  # also collect items that are close in meaning
    ("topics", "reach", "TEXT NOT NULL DEFAULT 'balanced'"),  # how close: narrow, balanced or broad
    ("topics", "auto_update", "INTEGER NOT NULL DEFAULT 0"),  # write "What is new" after a scrape
    ("topics", "visited_at", "TEXT NOT NULL DEFAULT ''"),  # when the page was last opened
    ("topics", "cover_url", "TEXT NOT NULL DEFAULT ''"),  # the one picture pinned for its card ('' = automatic)
]


def connect() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        # isolation_level=None -> autocommit; every statement is its own transaction.
        conn = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        _local.conn = conn
    return conn


def close() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


def init() -> None:
    conn = connect()
    conn.executescript(SCHEMA)
    for table, column, definition in ADDED_COLUMNS:
        if column not in {found["name"] for found in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


@contextmanager
def transaction():
    """Several statements that happen together or not at all (each statement is its own transaction otherwise)."""
    conn = connect()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def rows(sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in connect().execute(sql, params).fetchall()]


def row(sql: str, params: tuple | list = ()) -> dict | None:
    found = connect().execute(sql, params).fetchone()
    return dict(found) if found else None


def scalar(sql: str, params: tuple | list = ()):
    found = connect().execute(sql, params).fetchone()
    return found[0] if found else None


def execute(sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
    return connect().execute(sql, params)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
