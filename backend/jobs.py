"""Background jobs: analysing a source, scraping, writing a briefing.

A job is a function `fn(job) -> result` run on a worker thread. It reports with
`job.log()` and `job.progress()`, and the dashboard polls `/api/jobs/<id>`.
Jobs are also written to the database so the Activity page survives a restart.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from . import db
from .errors import ScrapeError

MAX_LOG_LINES = 400
ACTIVE = ("queued", "running")


class JobCancelled(Exception):
    pass


class JobError(Exception):
    """A job failed for a reason that should be shown to the user as-is (no traceback needed)."""


class Job:
    def __init__(self, kind: str, title: str, source_id: int | None, topic_id: int | None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.title = title
        self.source_id = source_id
        self.topic_id = topic_id
        self.status = "queued"
        self.logs: list[dict] = []
        self.progress_state: dict = {}
        self.result = None
        self.usage: dict = {}
        self.error = ""
        self.created_at = db.now()
        self.started_at = ""
        self.finished_at = ""
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._last_save = 0.0

    # -- used by the job function ------------------------------------------------

    def log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self.logs.append({"t": db.now(), "level": level, "msg": message})
            if len(self.logs) > MAX_LOG_LINES:
                del self.logs[1:len(self.logs) - MAX_LOG_LINES + 1]
        self.save(throttle=True)

    def progress(self, done: int, total: int | None = None, label: str = "") -> None:
        self.progress_state = {"done": done, "total": total, "label": label}
        self.save(throttle=True)

    def check_cancelled(self) -> None:
        if self._cancel.is_set():
            raise JobCancelled()

    # -- bookkeeping ---------------------------------------------------------------

    def cancel(self) -> None:
        self._cancel.set()

    def as_dict(self, with_logs: bool = True) -> dict:
        data = {
            "id": self.id, "kind": self.kind, "title": self.title, "source_id": self.source_id,
            "topic_id": self.topic_id, "status": self.status, "progress": self.progress_state,
            "result": self.result, "usage": self.usage, "error": self.error, "created_at": self.created_at,
            "started_at": self.started_at, "finished_at": self.finished_at,
        }
        if with_logs:
            with self._lock:
                data["logs"] = list(self.logs)
        return data

    def save(self, throttle: bool = False) -> None:
        now = time.monotonic()
        if throttle and now - self._last_save < 1.0:
            return
        self._last_save = now
        with self._lock:
            logs = json.dumps(self.logs)
        db.execute(
            """INSERT INTO jobs(id, kind, title, source_id, topic_id, status, progress, logs, result, usage, error,
                                created_at, started_at, finished_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status, progress=excluded.progress, logs=excluded.logs,
                   result=excluded.result, usage=excluded.usage, error=excluded.error,
                   started_at=excluded.started_at, finished_at=excluded.finished_at""",
            (self.id, self.kind, self.title, self.source_id, self.topic_id, self.status,
             json.dumps(self.progress_state), logs, json.dumps(self.result), json.dumps(self.usage), self.error,
             self.created_at, self.started_at, self.finished_at),
        )


class JobManager:
    def __init__(self, workers: int = 3):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, title: str, fn: Callable[[Job], object], *,
               source_id: int | None = None, topic_id: int | None = None) -> Job:
        job = Job(kind, title, source_id, topic_id)
        with self._lock:
            self._jobs[job.id] = job
        job.save()
        self._pool.submit(self._run, job, fn)
        return job

    def _run(self, job: Job, fn: Callable[[Job], object]) -> None:
        job.status = "running"
        job.started_at = db.now()
        job.save()
        try:
            job.result = fn(job)
            job.status = "done"
        except JobCancelled:
            job.status = "cancelled"
            job.log("Cancelled.", "warn")
        except (JobError, ScrapeError) as error:
            job.status = "error"
            job.error = str(error)
            job.log(str(error), "error")
        except Exception as error:  # a bug or an unexpected library failure: keep the trace for the Activity page
            job.status = "error"
            job.error = f"{type(error).__name__}: {error}"
            job.log(traceback.format_exc(), "error")
        finally:
            job.finished_at = db.now()
            job.save()
            db.close()

    def get(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        if job:
            return job.as_dict()
        stored = db.row("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return _decode(stored) if stored else None

    def recent(self, limit: int = 50) -> list[dict]:
        stored = db.rows(
            "SELECT id, kind, title, source_id, topic_id, status, progress, usage, error, created_at, started_at,"
            " finished_at FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        listed = []
        for entry in stored:
            live = self._jobs.get(entry["id"])
            listed.append(live.as_dict(with_logs=False) if live else _decode(entry))
        return listed

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job and job.status in ACTIVE:
            job.cancel()
            return True
        return False

    def active_for_source(self, source_id: int, kinds: tuple[str, ...]) -> Job | None:
        for job in list(self._jobs.values()):
            if job.source_id == source_id and job.kind in kinds and job.status in ACTIVE:
                return job
        return None

    def mark_interrupted(self) -> None:
        """Jobs that were running when the app was closed can never finish."""
        db.execute(
            "UPDATE jobs SET status = 'error', error = 'Interrupted: the app was closed while this was running',"
            " finished_at = ? WHERE status IN ('queued', 'running')", (db.now(),))


def _decode(stored: dict) -> dict:
    for key in ("progress", "logs", "result", "usage"):
        if key in stored:
            stored[key] = json.loads(stored[key])
    return stored


manager = JobManager()
