"""Site scrapers: code written for one specific site, for when a recipe of selectors is not good enough.

One file per site. Each holds a `SiteScraper` subclass decorated with `@scrapers.register`; it then shows up
under *Add source* in the dashboard, and `python -m backend.scrapers test <name>` tries it against the live
site without storing anything. The `scraper` connector is what runs them during a scrape.

`CLAUDE.md` in the project root describes how a new one is built.
"""

from ..registry import autodiscover
from .base import Page, SiteScraper, Stream, scrapers

autodiscover(__name__, __path__)

__all__ = ["Page", "SiteScraper", "Stream", "scrapers"]
