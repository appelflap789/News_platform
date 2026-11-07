"""The web app: the JSON API under /api and the built dashboard for everything else."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, addons, config, db, scheduler
from .api import routers
from .errors import ScrapeError
from .jobs import JobError, manager

NOT_BUILT = """<body style="font-family:system-ui;background:#0e1014;color:#e7e9ee;padding:48px;line-height:1.6">
<h2>The dashboard has not been built yet</h2>
<p>Run <code>npm install</code> and <code>npm run build</code> inside the <code>frontend</code> folder,
then reload this page. The API itself is running: see <a style="color:#7aa2ff" href="/docs">/docs</a>.</p></body>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    addons.init()
    manager.mark_interrupted()
    scheduler.start()
    from .api.system import start_embedding

    start_embedding()  # items stored before embeddings existed, or while they were switched off
    yield
    scheduler.stop()


app = FastAPI(title="News Scraper Platform", version=__version__, lifespan=lifespan)

for router in [*routers, *addons.routers()]:  # the add-ons' routes too (backend/addons)
    app.include_router(router)


@app.exception_handler(ScrapeError)
@app.exception_handler(JobError)
async def expected_failure(request: Request, error: Exception) -> JSONResponse:
    """A site refused, a selector was wrong, Claude is not configured: report it, do not crash."""
    return JSONResponse({"detail": str(error)}, status_code=400)


if (config.FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=config.FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def dashboard(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    index = config.FRONTEND_DIST / "index.html"
    if not index.is_file():
        return HTMLResponse(NOT_BUILT)
    static = (config.FRONTEND_DIST / path).resolve()
    if path and static.is_file() and config.FRONTEND_DIST.resolve() in static.parents:
        return FileResponse(static)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})
