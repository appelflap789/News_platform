"""PDF documents (reports, papers)."""

from __future__ import annotations

import io
import logging
import re

from ..fetchers import FetchResult
from ..util import clean, parse_date
from .base import Extracted, ExtractError, Extractor, extractors


logging.getLogger("pypdf").setLevel(logging.ERROR)  # it warns about every unusual font, on every page


def pdf_text(content: bytes, url: str = "") -> tuple[str, dict]:
    """(text, metadata) of a PDF. Raises ExtractError for scanned, broken or protected files."""
    from pypdf import PdfReader
    from pypdf.errors import DependencyError, PyPdfError

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            reader.decrypt("")
        pages = [page.extract_text() or "" for page in reader.pages]
        info = reader.metadata or {}
    except DependencyError as error:  # encrypted, and what would open it is not installed
        raise ExtractError(f"The PDF {url} is protected (encrypted) and cannot be read here") from error
    except (PyPdfError, ValueError, KeyError, OSError) as error:
        raise ExtractError(f"Could not read the PDF {url}: {error}") from error

    paragraphs: list[str] = []
    for page in pages:
        page = re.sub(r"(\w)-\n(\w)", r"\1\2", page)  # re-join words hyphenated across lines
        for block in re.split(r"\n\s*\n", page):
            block = clean(block)
            if block:
                paragraphs.append(block)
    text = "\n\n".join(paragraphs)
    if len(text) < 200:
        raise ExtractError(f"The PDF {url} has no text layer (probably a scan)")
    metadata = {
        "title": clean(str(info.get("/Title") or "")),
        "author": clean(str(info.get("/Author") or "")),
        "published": parse_date(_pdf_date(str(info.get("/CreationDate") or ""))),
        "pages": len(pages),
    }
    return text, metadata


def _pdf_date(raw: str) -> str:
    """D:20240312101500+01'00' -> 2024-03-12T10:15:00"""
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?", raw)
    if not match:
        return ""
    year, month, day, hour, minute, second = match.groups()
    return f"{year}-{month}-{day}T{hour or '00'}:{minute or '00'}:{second or '00'}"


def looks_like_title(title: str) -> bool:
    return 8 <= len(title) <= 250 and not re.search(r"\.(docx?|indd|pdf|pptx?)$|^untitled|^microsoft word", title, re.I)


@extractors.register
class PdfExtractor(Extractor):
    name = "pdf"
    label = "PDF document"
    description = "Takes the text and metadata out of a PDF."
    priority = 10

    def matches(self, result: FetchResult) -> bool:
        return result.is_pdf

    def extract(self, result: FetchResult, rules: dict[str, str], ctx) -> Extracted:
        text, metadata = pdf_text(result.content, result.url)
        title = metadata["title"] if looks_like_title(metadata["title"]) else ""
        if not title:
            title = next((p for p in text.split("\n\n") if 8 <= len(p) <= 200), "")
        return Extracted(
            title=title,
            author=metadata["author"],
            published=metadata["published"],
            text=text,
            pdf_url=result.url,
            content_type="document",
        )
