"""Built scrapers: which ones exist, and adding one to the library as a source."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db
from ..jobs import manager
from ..pipeline.scrape import scrape_source
from ..scrapers import scrapers
from ..scrapers._sources import add_source, describe_all, sources_by_scraper

router = APIRouter(prefix="/api")


class AddRequest(BaseModel):
    scrape_now: bool = True
    skip_walled: bool = False  # leave out items whose own page is behind a login or paywall, or refuses


@router.get("/scrapers")
def list_scrapers() -> list[dict]:
    return describe_all()


@router.post("/scrapers/{name}/add")
def add_scraper(name: str, request: AddRequest) -> dict:
    if name not in scrapers.names():
        raise HTTPException(404, f"There is no scraper called '{name}'.")
    if name in sources_by_scraper():
        raise HTTPException(409, "This scraper is already one of your sources.")
    scraper = scrapers.get(name)
    source_id = add_source(scraper)
    db.execute("UPDATE sources SET skip_walled = ? WHERE id = ?", (int(request.skip_walled), source_id))
    job = None
    if request.scrape_now:
        job = manager.submit("scrape", f"Scrape: {scraper.label}", lambda job: scrape_source(source_id, job),
                             source_id=source_id)
    return {"id": source_id, "job_id": job.id if job else None}
