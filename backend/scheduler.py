"""Automatic updates: scrape sources that have an update interval, when they are due.

*Every day* is a time of day, not 24 hours after the last scrape (which drifts with every run): such a source
is due once the day's scrape time (Settings → Scraping) has passed since it was last scraped. Every other
interval counts from the last scrape."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, db
from .jobs import manager
from .pipeline.scrape import scrape_source

CHECK_EVERY_SECONDS = 60
DAILY = 1440  # the interval "Every day"
_stop = threading.Event()


def daily_slot(now: datetime) -> datetime:
    """The last time the daily scrape was due: today at the set time, or yesterday when that is still to come."""
    hour, minute = (int(part) for part in str(config.get("daily_scrape_time")).split(":"))
    local = now.astimezone(ZoneInfo(config.TIMEZONE))
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot = (local - timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    return slot.astimezone(timezone.utc)


def due_sources(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    slot = daily_slot(now)
    due = []
    for source in db.rows("SELECT id, name, interval_minutes, last_scraped_at FROM sources WHERE interval_minutes > 0"):
        last = source["last_scraped_at"]
        if last:
            last_time = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if source["interval_minutes"] == DAILY:
                if last_time >= slot:
                    continue
            elif now - last_time < timedelta(minutes=source["interval_minutes"]):
                continue
        due.append(source)
    return due


def tick() -> int:
    started = 0
    for source in due_sources():
        if manager.active_for_source(source["id"], ("scrape", "enrich", "translate")):
            continue
        source_id = source["id"]
        manager.submit("scrape", f"Scheduled update: {source['name']}",
                       lambda job, source_id=source_id: scrape_source(source_id, job), source_id=source_id)
        started += 1
    return started


def _loop() -> None:
    while not _stop.wait(CHECK_EVERY_SECONDS):
        try:
            tick()
        except Exception:  # the scheduler must outlive a bad tick (e.g. a locked database)
            pass
        finally:
            db.close()


def start() -> None:
    _stop.clear()
    threading.Thread(target=_loop, name="scheduler", daemon=True).start()


def stop() -> None:
    _stop.set()
