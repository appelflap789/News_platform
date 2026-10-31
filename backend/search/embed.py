"""Embeddings: for every item a list of numbers that stands for what it is about.

Two texts on the same subject get lists that lie close together, whatever words or language they use. That
is what lets a search for "Is Russia going to attack NATO?" find a Dutch column, and a topic collect items
that never use its terms.

The lists are made by a small multilingual model that runs on this computer (through onnxruntime; nothing is
sent anywhere and it costs nothing). They are stored in the `embeddings` table and held in memory as one
matrix, which is searched whole: at 100,000 items that takes about five milliseconds.
"""

from __future__ import annotations

import importlib.util
import os
import re
import threading
import warnings
import zlib

from .. import config, db
from ..jobs import JobError

try:
    import numpy as np
except ImportError:  # the platform runs without it; only everything "by meaning" is switched off
    np = None

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
# The model reads about the first hundred words. It is given the title and a summary, never the opening of
# the stored text: that is too often a copyright page or a line of boilerplate, and items then group by
# where they come from instead of by what they are about.
SUMMARY_CHARS = 500
BATCH = 64
# Every item in a library of news and papers has something in common ("this is about politics and energy",
# and a little of "this is Dutch"), and that shared part hides the differences that matter. So the library's
# average embedding is taken off every item, which is what makes "close" mean "about the same thing". With
# few items the average says more about those items than about the library, so it starts at this size; below
# it the embeddings are used as they are and every threshold is a little stricter (`bar`).
CENTRE_FROM = 50
UNCENTRED_EXTRA = 0.10
QUERY_CACHE = 300
SHARED_LINE = re.compile(r"Shared in r/\S+ by u/\S+: \S+")  # the closing line of an article shared on Reddit


class Unavailable(JobError):
    """Embeddings cannot be made right now; the message says why, for the user."""


class LocalModel:
    """The real thing: a multilingual sentence model, downloaded once into the data folder."""

    name = MODEL

    def __init__(self) -> None:
        from fastembed import TextEmbedding

        config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self._model = TextEmbedding(MODEL, cache_dir=str(config.MODELS_DIR))

    def embed(self, texts: list[str]):
        return np.array(list(self._model.embed(texts, batch_size=32)), dtype=np.float32)


class HashModel:
    """A stand-in that needs no download, used by the tests: it counts words into 256 buckets, so texts that
    share words come out close. It knows nothing about meaning."""

    name = "hash-256"
    DIM = 256

    def embed(self, texts: list[str]):
        out = np.zeros((len(texts), self.DIM), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in re.findall(r"\w+", text.lower()):
                if len(word) > 2:
                    out[row, zlib.crc32(word[:5].encode("utf-8")) % self.DIM] += 1.0
        return out


_model = None
_model_error = ""
_model_lock = threading.Lock()
_index = None
_index_lock = threading.Lock()
_queries: dict[str, object] = {}


def _wanted() -> type:
    return HashModel if os.environ.get("NSP_EMBEDDER") == "hash" else LocalModel


def model_name() -> str:
    return _wanted().name


def _normalised(vectors):
    lengths = np.linalg.norm(vectors, axis=1, keepdims=True)
    lengths[lengths == 0] = 1.0
    return (vectors / lengths).astype(np.float32)


def missing() -> str:
    """Why embeddings cannot be used at all, or '' when they can."""
    if not config.get("meaning_enabled"):
        return "It is switched off in Settings."
    if np is None or (_wanted() is LocalModel and importlib.util.find_spec("fastembed") is None):
        return ("The packages for it are not installed. Run this once in the platform's folder: "
                r".venv\Scripts\python.exe -m pip install -r requirements.txt")
    return ""


def encode(texts: list[str]):
    """One row of numbers per text, each of length 1."""
    global _model, _model_error
    reason = missing()
    if reason:
        raise Unavailable(f"Items cannot be embedded. {reason}")
    with _model_lock:
        if _model is None or not isinstance(_model, _wanted()):
            try:
                _model = _wanted()()
                _model_error = ""
            except Exception as error:  # no internet for the first download, a blocked file, a full disk
                _model_error = (f"The embedding model could not be loaded ({type(error).__name__}: {error}). "
                                f"It is downloaded once, about 240 MB, so the first time needs internet.")
                raise Unavailable(_model_error) from error
        return _normalised(_model.embed(texts))


def encode_query(text: str):
    """The embedding of something typed: a search, a topic's name and description."""
    key = f"{model_name()}|{text}"
    found = _queries.get(key)
    if found is None:
        found = encode([text])[0]
        if len(_queries) >= QUERY_CACHE:
            _queries.clear()
        _queries[key] = found
    return found


def text_for(article: dict) -> str:
    """What is embedded for an item: its title and its summary (Claude's when there is one)."""
    summary = article["ai_summary"] or article["summary"] or article["text"][:SUMMARY_CHARS]
    summary = " ".join(SHARED_LINE.sub("", summary).split())
    return f"{article['title']}. {summary[:SUMMARY_CHARS]}".strip()


def pending() -> int:
    return db.scalar(
        "SELECT COUNT(*) FROM articles a LEFT JOIN embeddings e ON e.article_id = a.id AND e.model = ?"
        " WHERE e.article_id IS NULL", (model_name(),)) or 0


def embed_pending(job=None) -> dict:
    """Embed every item that has no embedding from the current model. Safe to stop and to run again."""
    waiting = [row["id"] for row in db.rows(
        "SELECT a.id FROM articles a LEFT JOIN embeddings e ON e.article_id = a.id AND e.model = ?"
        " WHERE e.article_id IS NULL ORDER BY a.id DESC", (model_name(),))]
    done = 0
    for start in range(0, len(waiting), BATCH):
        if job:
            job.check_cancelled()
            job.progress(done, len(waiting), "Working out what the items are about")
        ids = waiting[start:start + BATCH]
        marks = ",".join("?" * len(ids))
        articles = db.rows(f"SELECT id, title, summary, ai_summary, SUBSTR(text, 1, {SUMMARY_CHARS}) AS text"
                           f" FROM articles WHERE id IN ({marks})", ids)
        if not articles:
            continue
        vectors = encode([text_for(article) for article in articles])
        for article, vector in zip(articles, vectors):
            # REPLACE, not UPDATE: the row gets a new `seq`, which is how the matrix in memory notices.
            db.execute("INSERT OR REPLACE INTO embeddings(article_id, model, vector) VALUES(?,?,?)",
                       (article["id"], model_name(), vector.tobytes()))
        done += len(articles)
    if job and waiting:
        job.progress(done, len(waiting), "Working out what the items are about")
    return {"embedded": done}


class Index:
    """Every embedding, as one matrix with a row per item, with the library's average taken off."""

    def __init__(self, ids: list[int], stored) -> None:
        self.ids = np.array(ids, dtype=np.int64)
        self.centre = stored.mean(axis=0) if len(ids) >= CENTRE_FROM else None
        self.matrix = stored if self.centre is None else _normalised(stored - self.centre)
        self.row = {article_id: position for position, article_id in enumerate(ids)}

    def __len__(self) -> int:
        return len(self.ids)

    def place(self, vector):
        """Put the embedding of something typed (a search, a topic's name) where the items are."""
        if self.centre is None:
            return vector
        moved = vector - self.centre
        return (moved / (np.linalg.norm(moved) or 1.0)).astype(np.float32)

    def bar(self, closeness: float) -> float:
        """A threshold as it applies to this library: the stated one, or stricter while it is small."""
        return closeness if self.centre is not None else closeness + UNCENTRED_EXTRA

    def rows_of(self, ids) -> list[int]:
        return [self.row[i] for i in ids if i in self.row]

    def vectors(self, ids):
        """The embeddings of these items (those that have one), in the order given."""
        return self.matrix[self.rows_of(ids)]


def index() -> Index:
    """The matrix, re-read from the database only when embeddings were added or removed."""
    global _index
    stamp = (model_name(), *db.connect().execute(
        "SELECT COUNT(*), COALESCE(MAX(seq), 0) FROM embeddings WHERE model = ?", (model_name(),)).fetchone())
    with _index_lock:
        if _index is None or _index[0] != stamp:
            stored = db.connect().execute(
                "SELECT article_id, vector FROM embeddings WHERE model = ? ORDER BY article_id",
                (model_name(),)).fetchall()
            if stored:
                matrix = np.frombuffer(b"".join(row[1] for row in stored), dtype=np.float32)
                matrix = matrix.reshape(len(stored), -1)
            else:
                matrix = np.zeros((0, 1), dtype=np.float32)
            _index = (stamp, Index([row[0] for row in stored], matrix))
        return _index[1]


def ready() -> bool:
    """Can things be found by meaning right now? Needs the switch, the packages and at least one embedding."""
    return not missing() and len(index()) > 0


def status() -> dict:
    """For the Settings page and /api/meta. `reason` is why nothing can be embedded, or what went wrong the
    last time it was tried (the next try may succeed: the model is downloaded on first use)."""
    total = db.scalar("SELECT COUNT(*) FROM articles") or 0
    waiting = pending() if np is not None else total
    return {
        "enabled": bool(config.get("meaning_enabled")),
        "available": not missing(),
        "reason": missing() or _model_error,
        "model": model_name(),
        "items": total,
        "embedded": total - waiting,
        "pending": waiting,
    }


def forget() -> None:
    """Drop what is held in memory: the loaded model, the matrix, the embedded queries."""
    global _model, _model_error, _index
    _model, _model_error, _index = None, "", None
    _queries.clear()


def refresh(job) -> dict:
    """The body of the job that embeds what is waiting (after a scrape, at start-up, from Settings)."""
    waiting = pending()
    if not waiting:
        job.log("Every item already has an embedding.")
        return {"embedded": 0}
    job.log(f"Working out what {waiting:,} items are about, with a model on this computer ({model_name()}). "
            f"The first time, the model is downloaded (about 240 MB).")
    result = embed_pending(job)
    job.log(f"Done: {result['embedded']:,} items embedded.")
    return result
