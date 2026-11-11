"""The ask add-on's routes. Finding passages and pricing a question is free; answering it starts a job."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ... import config, db
from ...ai import client as ai
from ...jobs import manager
from . import answer, find, passages, store

router = APIRouter(prefix="/api/ask")

# question id -> the job answering it, so that its page shows the job also after a reload
_working: dict[int, str] = {}


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    topic_id: int | None = None
    source_id: int | None = None
    since: str = Field("", pattern="^(|month|quarter|year)$")


def _scope(body: Question) -> dict:
    """What the question is asked of, with names, as it is kept with the question."""
    scope: dict = {}
    if body.topic_id:
        topic = db.row("SELECT name FROM topics WHERE id = ?", (body.topic_id,))
        if topic is None:
            raise HTTPException(404, "Topic not found.")
        scope.update(topic_id=body.topic_id, topic_name=topic["name"])
    if body.source_id:
        source = db.row("SELECT name FROM sources WHERE id = ?", (body.source_id,))
        if source is None:
            raise HTTPException(404, "Source not found.")
        scope.update(source_id=body.source_id, source_name=source["name"])
    if body.since:
        scope["since"] = body.since
    return scope


def _found(body: Question) -> find.Found:
    return find.find(body.question.strip(), topic_id=body.topic_id, source_id=body.source_id, since=body.since)


@router.get("/status")
def status() -> dict:
    """How far the library is split into passages, and which model answers."""
    chosen = answer.model()
    return {**passages.status(), "model": chosen, "model_label": config.model_label(chosen),
            "can_answer": ai.available()}


@router.post("/prepare")
def prepare() -> dict:
    """Split what is not split yet. Free."""
    job_id = passages.start()
    return {"job_id": job_id}


@router.post("/plan")
def plan(body: Question) -> dict:
    """What a question would read and cost. Free: nothing is sent to Claude."""
    _scope(body)
    found = _found(body)
    return {**answer.plan(found, body.question), "titles": [
        {"article_id": item["id"], "title": item["title"], "source_name": item["source_name"]}
        for item in found.items[:8]]}


@router.post("")
def ask(body: Question) -> dict:
    """Ask a question: it is kept, and Claude answers it in a job."""
    if not ai.available():
        raise HTTPException(400, "This needs an Anthropic API key. Add one on the Settings page.")
    scope = _scope(body)
    question_id = store.add_question(" ".join(body.question.split()), scope, answer.model())
    job = manager.submit("ask", f"Answering: {body.question.strip()[:80]}",
                         lambda job: answer.answer(question_id, job))
    _working[question_id] = job.id
    return {"id": question_id, "job_id": job.id}


@router.get("/questions")
def questions() -> list[dict]:
    return store.questions()


@router.get("/questions/{question_id}")
def question(question_id: int) -> dict:
    found = store.question(question_id)
    if found is None:
        raise HTTPException(404, "Question not found.")
    job_id = _working.get(question_id)
    job = manager.get(job_id) if job_id else None
    found["job_id"] = job_id if job and job["status"] in ("queued", "running") else None
    found["model_label"] = config.model_label(found["model"]) if found["model"] else ""
    present = {row["id"] for row in db.rows(
        f"SELECT id FROM articles WHERE id IN ({','.join('?' * len(found['sources']))})",
        [s["article_id"] for s in found["sources"]])} if found["sources"] else set()
    for source in found["sources"]:
        source["gone"] = source["article_id"] not in present
    return found


@router.delete("/questions/{question_id}")
def remove(question_id: int) -> dict:
    if not store.remove(question_id):
        raise HTTPException(404, "Question not found.")
    return {"removed": True}
