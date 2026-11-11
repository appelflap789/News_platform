"""The ask add-on's own tables: the passages every item is split into, their embeddings, and the questions asked.

Like every add-on's tables they refer to the platform's items only by number: no foreign key to `articles` and no
trigger on it, so that deleting the add-on cannot break anything. Instead `ask_done` keeps a fingerprint of the
words each item was split from (`STAMP`); an item whose fingerprint no longer matches (a translation, a video
written up) is split again, and the passages of items that left the library are swept up by the next run
(passages.sweep). The questions keep the items they cite inside their JSON columns, so an answer stays readable
when an item it cites is gone.
"""

from __future__ import annotations

import json

from ... import db

SCHEMA = """
-- An item's text in pieces of about a hundred words. Position 0 is the item's title and summary.
CREATE TABLE IF NOT EXISTS ask_passages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL,
    position   INTEGER NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ask_passages_article ON ask_passages(article_id, position);

-- The embedding of each passage. AUTOINCREMENT ids only grow, so "has anything changed" is a cheap question.
CREATE TABLE IF NOT EXISTS ask_vectors (
    passage_id INTEGER PRIMARY KEY REFERENCES ask_passages(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    vector     BLOB NOT NULL
);

-- Which items have been split: from which words (`stamp`) and with which embedding model.
CREATE TABLE IF NOT EXISTS ask_done (
    article_id INTEGER PRIMARY KEY,
    stamp      TEXT NOT NULL,
    model      TEXT NOT NULL,
    passages   INTEGER NOT NULL DEFAULT 0,
    done_at    TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS ask_fts USING fts5(
    text, content='ask_passages', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS ask_passages_ai AFTER INSERT ON ask_passages BEGIN
    INSERT INTO ask_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS ask_passages_ad AFTER DELETE ON ask_passages BEGIN
    INSERT INTO ask_fts(ask_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;

-- A question you asked, and Claude's answer from the library.
CREATE TABLE IF NOT EXISTS ask_questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question    TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT '{}',   -- {topic_id, source_id, since} as asked, with their names
    status      TEXT NOT NULL DEFAULT 'waiting',  -- waiting | done | failed
    answer      TEXT NOT NULL DEFAULT '',     -- Markdown, citing items as [1], [2]
    sources     TEXT NOT NULL DEFAULT '[]',   -- the items cited: {n, article_id, title, url, source_name, date, quotes}
    read        TEXT NOT NULL DEFAULT '[]',   -- the other items Claude was given but did not cite
    passages    INTEGER NOT NULL DEFAULT 0,   -- how many passages it was given
    model       TEXT NOT NULL DEFAULT '',
    cost_usd    REAL NOT NULL DEFAULT 0,
    error       TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    answered_at TEXT NOT NULL DEFAULT ''
);
"""

JSON_COLUMNS = ("scope", "sources", "read")
# The fingerprint of the words an item is split from, as SQL over `articles a`. Lengths are enough: a translation,
# a new summary or a video written up changes at least one of them, and comparing them costs nothing.
STAMP = "LENGTH(a.title) || ':' || LENGTH(a.summary) || ':' || LENGTH(a.ai_summary) || ':' || LENGTH(a.text)"


def init() -> None:
    db.connect().executescript(SCHEMA)


def _decode(found: dict | None) -> dict | None:
    if found is None:
        return None
    for column in JSON_COLUMNS:
        if column in found:
            found[column] = json.loads(found[column])
    return found


def add_question(question: str, scope: dict, model: str) -> int:
    return db.execute("INSERT INTO ask_questions(question, scope, model, created_at) VALUES(?,?,?,?)",
                      (question, json.dumps(scope), model, db.now())).lastrowid


def question(question_id: int) -> dict | None:
    return _decode(db.row("SELECT * FROM ask_questions WHERE id = ?", (question_id,)))


def questions(limit: int = 200) -> list[dict]:
    """Newest first, without the answers themselves."""
    out = []
    for row in db.rows("SELECT id, question, scope, status, sources, cost_usd, model, error, created_at, answered_at"
                       " FROM ask_questions ORDER BY id DESC LIMIT ?", (limit,)):
        row = _decode(row)
        row["cited"] = len(row.pop("sources"))
        out.append(row)
    return out


def update(question_id: int, **fields) -> None:
    for column in JSON_COLUMNS:
        if column in fields:
            fields[column] = json.dumps(fields[column])
    assignments = ", ".join(f"{column} = ?" for column in fields)
    db.execute(f"UPDATE ask_questions SET {assignments} WHERE id = ?", (*fields.values(), question_id))


def remove(question_id: int) -> bool:
    return db.execute("DELETE FROM ask_questions WHERE id = ?", (question_id,)).rowcount > 0
