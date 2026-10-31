"""Connectors: how the items of a feed are listed (RSS, an HTML listing, a sitemap, Reddit, ...).

To support a new kind of source, add a module here with a `Connector` subclass
decorated with `@connectors.register`. Declare its options as `fields`; they
then appear in the recipe editor and in the schema Claude fills in.
"""

from ..registry import autodiscover
from .base import Connector, ConnectorError, Context, Item, ListPage, connectors

autodiscover(__name__, __path__)

__all__ = ["Connector", "ConnectorError", "Context", "Item", "ListPage", "connectors"]
