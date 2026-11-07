"""HTTP API. One module per area; `routers` is what `main.py` mounts.

To add an area, create a module with a `router = APIRouter(prefix="/api")` and
list it here.
"""

from . import articles, links, scrape_log, scrapers, sources, system, topics

routers = [sources.router, scrapers.router, links.router, articles.router, topics.router, system.router,
           scrape_log.router]
