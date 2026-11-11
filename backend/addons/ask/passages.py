"""Every item split into passages of about a hundred words, each with an embedding of its own.

One embedding per item (search/embed.py) says what an item is about as a whole; it cannot find the one paragraph of
a 60-page report that answers a question. So for asking, each item's text is cut into passages, at paragraph and
sentence ends, and each passage is embedded with the same free model on this computer. Passage 0 is the item's
title and summary, so that also an item without text (a feed-only source) can be found and cited.

The work runs as a job of its own: once for the whole library (about 55,000 passages for 1,800 items, which takes
a while), then after every scrape for what is new. Nothing here costs money.
"""

from __future__ import annotations

import re
import threading

from ... import db
from ...jobs import manager
from ...search import embed
from . import store

TARGET_CHARS = 600  # a passage is cut once it reaches about this length (about a hundred words) ...
MAX_CHARS = 900  # ... and is never longer than this. The model reads about the first 128 word pieces.
MIN_WORDS = 12  # shorter pieces (a page number, a heading on its own, a line of a table) are left out
MIN_LETTERS = 0.55  # ... and so are pieces that are mostly numbers, URLs or symbols (tables, references)
LEAD_SUMMARY_CHARS = 700
ITEMS_PER_BATCH = 16
JOB_KIND = "ask-passages"

SENTENCE_END = re.compile(r"(?<=[.!?…])[\"”’)\]]*\s+(?=[\"“‘(\[]?[A-Z0-9À-ÖØ-Þ])")
PARAGRAPH = re.compile(r"\n\s*\n")
URL = re.compile(r"https?://\S+|www\.\S+")
# What reference lists and footnotes are made of. They match a question on its names and say nothing.
REF_LINK = re.compile(r"https?:\s*/\s*/|www\.|tinyurl|\.(?:com|org|gov|int|eu|nl|de|uk)/", re.IGNORECASE)
REF_SEEN = re.compile(r"\b(?:accessed|available at|retrieved|zuletzt eingesehen|geraadpleegd|consult[ée] le|ibid|"
                      r"op\. cit|et al)\b", re.IGNORECASE)
REF_TITLE = re.compile(r"[‘“»„\"][^’”«“\"]{8,160}[’”«“\"]")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
REFERENCE_MARKS = 5  # per hundred words; measured on a copy of the owner's library, see the README
PDF_JUNK = re.compile(r"/uni[0-9A-Fa-f]{4}")
PAGE_MARK = re.compile(r"^(page|p\.|pagina|seite)?\s*\d+(\s*(of|/|van)\s*\d+)?$", re.IGNORECASE)

_index = None
_index_lock = threading.Lock()


# --- splitting ---------------------------------------------------------------------------------

def _pieces(paragraph: str) -> list[str]:
    """A paragraph in pieces no longer than MAX_CHARS: whole sentences where it can, words where it must."""
    if len(paragraph) <= MAX_CHARS:
        return [paragraph]
    out = []
    for sentence in SENTENCE_END.split(paragraph):
        while len(sentence) > MAX_CHARS:
            cut = sentence.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > MAX_CHARS // 2 else MAX_CHARS
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


def _mostly_words(text: str) -> bool:
    """Not a page number, a row of figures or a list of links."""
    if PAGE_MARK.match(text):
        return False
    plain = URL.sub("", text).replace(" ", "")
    letters = sum(1 for ch in plain if ch.isalpha())
    return bool(plain) and letters / len(plain) >= MIN_LETTERS


def reference_list(text: str) -> bool:
    """A stretch of footnotes or a bibliography: links, "accessed", quoted titles with dates."""
    links, seen = len(REF_LINK.findall(text)), len(REF_SEEN.findall(text))
    titles = len(REF_TITLE.findall(text)) if YEAR.search(text) else 0
    if not links and not seen and titles < 3:
        return False
    return (2 * links + 2 * seen + titles) * 100 / max(1, len(text.split())) >= REFERENCE_MARKS


def split(text: str) -> list[str]:
    """The text in passages of about TARGET_CHARS, each ending at a paragraph or sentence end when it can."""
    pieces: list[str] = []
    for paragraph in PARAGRAPH.split(PDF_JUNK.sub(" ", text or "")):
        paragraph = " ".join(paragraph.split())
        if paragraph:
            pieces.extend(piece for piece in _pieces(paragraph) if _mostly_words(piece))
    passages: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) > TARGET_CHARS:
            passages.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        passages.append(current)
    return [passage for passage in passages if len(passage.split()) >= MIN_WORDS and not reference_list(passage)]


def lead(article: dict) -> str:
    """Passage 0: the title and the summary (Claude's when there is one)."""
    summary = " ".join((article["ai_summary"] or article["summary"] or "").split())
    if len(summary) > LEAD_SUMMARY_CHARS:
        summary = summary[:LEAD_SUMMARY_CHARS].rsplit(" ", 1)[0] + " …"
    title = " ".join((article["title"] or "").split())
    return f"{title}. {summary}".strip() if summary else title


def passages_of(article: dict) -> list[str]:
    """What an item is split into: its lead, then its text. A text that starts with the summary does not
    repeat it."""
    out = [lead(article)]
    body = split(article["text"])
    if body and article["summary"] and " ".join(article["summary"].split())[:120] in body[0]:
        out[0] = " ".join((article["title"] or "").split()) or out[0]
    out.extend(body)
    return [passage for passage in out if passage]


# --- the job -----------------------------------------------------------------------------------

def _pending_sql(columns: str) -> str:
    return (f"SELECT {columns} FROM articles a LEFT JOIN ask_done d ON d.article_id = a.id"
            f" WHERE d.article_id IS NULL OR d.stamp != {store.STAMP} OR d.model != ?")


def pending() -> int:
    if embed.np is None:
        return 0
    return db.scalar(_pending_sql("COUNT(*)"), (embed.model_name(),)) or 0


def sweep() -> int:
    """Take out the passages of items that have left the library. Returns how many items that was."""
    gone = [row["article_id"] for row in db.rows(
        "SELECT d.article_id FROM ask_done d LEFT JOIN articles a ON a.id = d.article_id WHERE a.id IS NULL")]
    gone += [row["article_id"] for row in db.rows(
        "SELECT DISTINCT p.article_id FROM ask_passages p LEFT JOIN ask_done d ON d.article_id = p.article_id"
        " LEFT JOIN articles a ON a.id = p.article_id WHERE a.id IS NULL AND d.article_id IS NULL")]
    for article_id in gone:
        with db.transaction() as conn:
            conn.execute("DELETE FROM ask_passages WHERE article_id = ?", (article_id,))
            conn.execute("DELETE FROM ask_done WHERE article_id = ?", (article_id,))
    return len(gone)


def _store(article: dict, texts: list[str], vectors) -> None:
    with db.transaction() as conn:
        conn.execute("DELETE FROM ask_passages WHERE article_id = ?", (article["id"],))
        for position, (text, vector) in enumerate(zip(texts, vectors)):
            passage_id = conn.execute("INSERT INTO ask_passages(article_id, position, text) VALUES(?,?,?)",
                                      (article["id"], position, text)).lastrowid
            conn.execute("INSERT INTO ask_vectors(passage_id, model, vector) VALUES(?,?,?)",
                         (passage_id, embed.model_name(), vector.tobytes()))
        conn.execute("INSERT OR REPLACE INTO ask_done(article_id, stamp, model, passages, done_at) VALUES(?,?,?,?,?)",
                     (article["id"], article["stamp"], embed.model_name(), len(texts), db.now()))


def split_pending(job=None) -> dict:
    """Split and embed every item that is not done yet, newest first. Safe to stop and to run again."""
    swept = sweep()
    waiting = [row["id"] for row in db.rows(_pending_sql("a.id") + " ORDER BY a.id DESC", (embed.model_name(),))]
    done = passages = 0
    for start in range(0, len(waiting), ITEMS_PER_BATCH):
        if job:
            job.check_cancelled()
            job.progress(done, len(waiting), "Splitting items into passages")
        ids = waiting[start:start + ITEMS_PER_BATCH]
        marks = ",".join("?" * len(ids))
        articles = db.rows(f"SELECT a.id, a.title, a.summary, a.ai_summary, a.text, {store.STAMP} AS stamp"
                           f" FROM articles a WHERE a.id IN ({marks})", ids)
        texts = {article["id"]: passages_of(article) for article in articles}
        everything = [text for article in articles for text in texts[article["id"]]]
        vectors = embed.encode(everything) if everything else []
        at = 0
        for article in articles:  # an item removed meanwhile is simply not there any more
            count = len(texts[article["id"]])
            _store(article, texts[article["id"]], vectors[at:at + count])
            at += count
            passages += count
        done += len(ids)
    if job and waiting:
        job.progress(done, len(waiting), "Splitting items into passages")
    return {"items": done, "passages": passages, "swept": swept}


def _job(job) -> dict:
    waiting = pending()
    job.log(f"Splitting {waiting:,} items into passages and working out what each is about, with the model on "
            f"this computer ({embed.model_name()}). Free; the first time this takes a while.")
    result = split_pending(job)
    job.log(f"Done: {result['items']:,} items, {result['passages']:,} passages.")
    return result


def running() -> str | None:
    found = next((job for job in manager.recent(30) if job["kind"] == JOB_KIND
                  and job["status"] in ("queued", "running")), None)
    return found["id"] if found else None


def start() -> str | None:
    """Start the job unless there is nothing to do, it cannot run, or it runs already. Returns its id."""
    if embed.missing():
        return None
    already = running()
    if already:
        return already
    if not pending() and not sweep():
        return None
    return manager.submit(JOB_KIND, "Preparing the library for questions", _job).id


def status() -> dict:
    total = db.scalar("SELECT COUNT(*) FROM articles") or 0
    waiting = pending()
    return {
        "items": total,
        "done": max(0, total - waiting),
        "waiting": waiting,
        "passages": db.scalar("SELECT COUNT(*) FROM ask_vectors WHERE model = ?", (embed.model_name(),)) or 0,
        "job_id": running(),
        "unavailable": embed.missing(),
    }


# --- the matrix in memory ------------------------------------------------------------------------

class PassageIndex(embed.Index):
    """Every passage embedding as one matrix, the library's average taken off as for the items, with the item
    each row belongs to."""

    def __init__(self, ids: list[int], stored, articles: list[int]) -> None:
        super().__init__(ids, stored)
        self.articles = embed.np.array(articles, dtype=embed.np.int64)


def index() -> PassageIndex:
    """Re-read from the database only when passages were added or removed."""
    global _index
    stamp = (embed.model_name(), *db.connect().execute(
        "SELECT COUNT(*), COALESCE(MAX(passage_id), 0) FROM ask_vectors WHERE model = ?",
        (embed.model_name(),)).fetchone())
    with _index_lock:
        if _index is None or _index[0] != stamp:
            stored = db.connect().execute(
                "SELECT v.passage_id, p.article_id, v.vector FROM ask_vectors v JOIN ask_passages p"
                " ON p.id = v.passage_id WHERE v.model = ? ORDER BY v.passage_id", (embed.model_name(),)).fetchall()
            np = embed.np
            if stored:
                matrix = np.frombuffer(b"".join(row[2] for row in stored), dtype=np.float32).reshape(len(stored), -1)
            else:
                matrix = np.zeros((0, 1), dtype=np.float32)
            _index = (stamp, PassageIndex([row[0] for row in stored], matrix, [row[1] for row in stored]))
        return _index[1]


def forget() -> None:
    global _index
    _index = None
