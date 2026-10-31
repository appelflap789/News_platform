"""Fetchers: how bytes are downloaded.

To add one (for example a headless browser for JavaScript-heavy sites), create
a module in this folder with a `Fetcher` subclass decorated with
`@fetchers.register`. A feed selects it with `"fetcher": "<name>"` in its recipe.
"""

from ..registry import autodiscover
from .base import FetchError, Fetcher, FetchResult, fetchers

autodiscover(__name__, __path__)

__all__ = ["FetchError", "FetchResult", "Fetcher", "fetchers"]
