"""The foresight add-on's own tables, and reading and writing them.

The tables are made by `init` when the platform starts. They refer to the platform's items only by number, inside
their JSON columns (never with a foreign key), so the platform can remove an item without knowing about them;
whatever reads an item from here expects it may be gone.
"""

from __future__ import annotations

import json

from ... import db

SCHEMA = """
-- A foresight: a trend, a weak signal or an event, what the library says about it, and what follows from it.
CREATE TABLE IF NOT EXISTS foresights (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    statement       TEXT NOT NULL DEFAULT '',
    kind            TEXT NOT NULL DEFAULT 'trend',      -- trend | signal | event
    horizon         TEXT NOT NULL DEFAULT 'years',      -- months | years | decades
    note            TEXT NOT NULL DEFAULT '',           -- what the owner knows, given to Claude as expert knowledge
    topic_id        INTEGER REFERENCES topics(id) ON DELETE SET NULL,  -- its literature is that topic's items
    terms           TEXT NOT NULL DEFAULT '[]',         -- the words its own literature is found by
    standing        TEXT NOT NULL DEFAULT '',           -- borne_out | partly | contested | thin ('' = not read)
    restated        TEXT NOT NULL DEFAULT '',           -- the statement as the library sees it
    reading         TEXT NOT NULL DEFAULT '',           -- what the library says, Markdown citing [n]
    reading_sources TEXT NOT NULL DEFAULT '[]',         -- the items read: {n, article_id, ..., stance, says}
    gaps            TEXT NOT NULL DEFAULT '[]',
    read_at         TEXT NOT NULL DEFAULT '',
    read_through    TEXT NOT NULL DEFAULT '',           -- the newest fetched_at among what was read
    links           TEXT NOT NULL DEFAULT '[]',         -- [{from, to, effect, why}] between consequences
    cost_usd        REAL NOT NULL DEFAULT 0,            -- what Claude has cost on it, all steps together
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT '',
    visited_at      TEXT NOT NULL DEFAULT ''
);

-- A consequence. Ring 1 follows from the foresight itself, ring 2 from a ring-1 consequence (its parent), ring 3
-- from a ring-2 one.
CREATE TABLE IF NOT EXISTS foresight_nodes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    foresight_id INTEGER NOT NULL REFERENCES foresights(id) ON DELETE CASCADE,
    parent_id    INTEGER REFERENCES foresight_nodes(id) ON DELETE CASCADE,
    ring         INTEGER NOT NULL,
    position     INTEGER NOT NULL DEFAULT 0,
    text         TEXT NOT NULL,
    mechanism    TEXT NOT NULL DEFAULT '',
    domain       TEXT NOT NULL DEFAULT '',
    horizon      TEXT NOT NULL DEFAULT '',
    likelihood   TEXT NOT NULL DEFAULT '',     -- a word of the PHIA probability yardstick
    basis        TEXT NOT NULL DEFAULT 'reasoning',  -- library | argued | reasoning | yours
    dampening    INTEGER NOT NULL DEFAULT 0,   -- pushes back against the others
    sources      TEXT NOT NULL DEFAULT '[]',   -- the items it rests on: {article_id, title, source_name, date, url}
    status       TEXT NOT NULL DEFAULT '',     -- from a re-check: strengthened | weakened | happening | contradicted
    status_why   TEXT NOT NULL DEFAULT '',
    status_at    TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',     -- the owner's
    outcome      TEXT NOT NULL DEFAULT '',     -- the owner's look back: happened | did_not | too_early
    expanded_at  TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_foresight_nodes ON foresight_nodes(foresight_id, ring, position);

-- What a news item would report if a consequence were happening ('for') or were not ('against'). Watched for
-- free after every scrape (watch.py); `seen` holds the items that matched.
CREATE TABLE IF NOT EXISTS foresight_signposts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id         INTEGER NOT NULL REFERENCES foresight_nodes(id) ON DELETE CASCADE,
    text            TEXT NOT NULL,
    direction       TEXT NOT NULL DEFAULT 'for',
    terms           TEXT NOT NULL DEFAULT '[]',
    seen            TEXT NOT NULL DEFAULT '[]',   -- [{id, at, earlier}]; earlier = already there when it was made
    checked_through TEXT NOT NULL DEFAULT '',     -- items fetched after this are still to be looked at
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_foresight_signposts ON foresight_signposts(node_id);

-- Every time the foresight was read again with the items that arrived since: what changed.
CREATE TABLE IF NOT EXISTS foresight_checks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    foresight_id INTEGER NOT NULL REFERENCES foresights(id) ON DELETE CASCADE,
    text         TEXT NOT NULL,
    standing     TEXT NOT NULL DEFAULT '',
    previous     TEXT NOT NULL DEFAULT '',     -- the standing before
    sources      TEXT NOT NULL DEFAULT '[]',
    changes      TEXT NOT NULL DEFAULT '[]',   -- [{node_id, status, why}]
    items        INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_foresight_checks ON foresight_checks(foresight_id, id);
"""

# Columns added after libraries already had these tables; `init` adds the ones a library lacks.
ADDED_COLUMNS: list[tuple[str, str, str]] = []

JSON_COLUMNS = {
    "foresights": ("terms", "reading_sources", "gaps", "links"),
    "foresight_nodes": ("sources",),
    "foresight_signposts": ("terms", "seen"),
    "foresight_checks": ("sources", "changes"),
}


def init() -> None:
    conn = db.connect()
    conn.executescript(SCHEMA)
    for table, column, definition in ADDED_COLUMNS:
        if column not in {found["name"] for found in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _decoded(table: str, row: dict | None) -> dict | None:
    if row is None:
        return None
    for column in JSON_COLUMNS[table]:
        row[column] = json.loads(row[column] or "[]")
    if table == "foresight_nodes":
        row["dampening"] = bool(row["dampening"])
    return row


def _encoded(value):
    return json.dumps(value) if isinstance(value, (list, dict)) else value


def foresight(foresight_id: int) -> dict | None:
    return _decoded("foresights", db.row("SELECT * FROM foresights WHERE id = ?", (foresight_id,)))


def foresights() -> list[dict]:
    return [_decoded("foresights", row) for row in db.rows("SELECT * FROM foresights ORDER BY id")]


def create(fields: dict) -> int:
    fields = {**fields, "created_at": db.now(), "updated_at": db.now(), "visited_at": db.now()}
    columns = ", ".join(fields)
    return db.execute(f"INSERT INTO foresights({columns}) VALUES({','.join('?' * len(fields))})",
                      [_encoded(value) for value in fields.values()]).lastrowid


def update(foresight_id: int, **fields) -> None:
    if not fields:
        return
    fields.setdefault("updated_at", db.now())
    assignments = ", ".join(f"{column} = ?" for column in fields)
    db.execute(f"UPDATE foresights SET {assignments} WHERE id = ?",
               [*(_encoded(value) for value in fields.values()), foresight_id])


def add_cost(foresight_id: int, usd: float) -> None:
    db.execute("UPDATE foresights SET cost_usd = cost_usd + ? WHERE id = ?", (usd, foresight_id))


def remove(foresight_id: int) -> None:
    db.execute("DELETE FROM foresights WHERE id = ?", (foresight_id,))


# --- consequences ---------------------------------------------------------------------------

def nodes(foresight_id: int) -> list[dict]:
    """The consequences, ring by ring, each ring in the order they were worked out."""
    return [_decoded("foresight_nodes", row) for row in db.rows(
        "SELECT * FROM foresight_nodes WHERE foresight_id = ? ORDER BY ring, parent_id, position, id",
        (foresight_id,))]


def node(node_id: int) -> dict | None:
    return _decoded("foresight_nodes", db.row("SELECT * FROM foresight_nodes WHERE id = ?", (node_id,)))


def add_node(foresight_id: int, parent_id: int | None, ring: int, fields: dict,
             signposts: list[dict] | None = None) -> int:
    """One consequence, after the ones already next to it, with its signposts."""
    position = db.scalar(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM foresight_nodes WHERE foresight_id = ? AND parent_id IS ?",
        (foresight_id, parent_id))
    fields = {**fields, "foresight_id": foresight_id, "parent_id": parent_id, "ring": ring, "position": position,
              "created_at": db.now()}
    columns = ", ".join(fields)
    node_id = db.execute(f"INSERT INTO foresight_nodes({columns}) VALUES({','.join('?' * len(fields))})",
                         [_encoded(value) for value in fields.values()]).lastrowid
    now = db.now()  # watched from now on; the same stamp in both says it was never looked at (watch.py)
    for signpost in signposts or []:
        db.execute(
            "INSERT INTO foresight_signposts(node_id, text, direction, terms, checked_through, created_at)"
            " VALUES(?,?,?,?,?,?)",
            (node_id, signpost["text"], signpost["direction"], json.dumps(signpost["terms"]), now, now))
    return node_id


def update_node(node_id: int, **fields) -> None:
    if fields:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        db.execute(f"UPDATE foresight_nodes SET {assignments} WHERE id = ?",
                   [*(_encoded(value) for value in fields.values()), node_id])


def remove_node(node_id: int) -> None:
    """A consequence and everything that was worked out from it."""
    db.execute("DELETE FROM foresight_nodes WHERE id = ?", (node_id,))


def remove_nodes(foresight_id: int) -> None:
    db.execute("DELETE FROM foresight_nodes WHERE foresight_id = ?", (foresight_id,))


# --- signposts and checks --------------------------------------------------------------------

def signposts(foresight_id: int | None = None) -> list[dict]:
    """The signposts of one foresight, or of all of them."""
    sql = ("SELECT s.*, n.foresight_id FROM foresight_signposts s JOIN foresight_nodes n ON n.id = s.node_id"
           + (" WHERE n.foresight_id = ?" if foresight_id else "") + " ORDER BY s.id")
    return [_decoded("foresight_signposts", row) for row in db.rows(sql, (foresight_id,) if foresight_id else ())]


def update_signpost(signpost_id: int, **fields) -> None:
    assignments = ", ".join(f"{column} = ?" for column in fields)
    db.execute(f"UPDATE foresight_signposts SET {assignments} WHERE id = ?",
               [*(_encoded(value) for value in fields.values()), signpost_id])


def checks(foresight_id: int) -> list[dict]:
    """The re-checks, newest first."""
    return [_decoded("foresight_checks", row) for row in db.rows(
        "SELECT * FROM foresight_checks WHERE foresight_id = ? ORDER BY id DESC", (foresight_id,))]


def add_check(foresight_id: int, fields: dict) -> int:
    fields = {**fields, "foresight_id": foresight_id, "created_at": db.now()}
    columns = ", ".join(fields)
    return db.execute(f"INSERT INTO foresight_checks({columns}) VALUES({','.join('?' * len(fields))})",
                      [_encoded(value) for value in fields.values()]).lastrowid
