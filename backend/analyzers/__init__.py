"""Analyzers: how a web address becomes a recipe.

* `claude`    - Claude explores the site with tools, tests its own recipe, and explains the structure.
* `heuristic` - no AI: finds feeds and sitemaps a site advertises.

To add another strategy, create a module here with an `Analyzer` subclass
decorated with `@analyzers.register`; it appears in the Add-source wizard.
"""

from ..registry import autodiscover
from .base import Analysis, Analyzer, analyzers

autodiscover(__name__, __path__)

__all__ = ["Analysis", "Analyzer", "analyzers"]
