"""Extractors: how one downloaded item (a web page, a PDF) becomes clean text plus metadata.

To support a new document type, add a module here with an `Extractor` subclass
decorated with `@extractors.register`. `pick()` chooses the first extractor,
by priority, whose `matches()` accepts the download.
"""

from ..registry import autodiscover
from .base import Extracted, ExtractError, Extractor, extractors, pick

autodiscover(__name__, __path__)

__all__ = ["ExtractError", "Extracted", "Extractor", "extractors", "pick"]
