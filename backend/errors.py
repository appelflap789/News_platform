"""Errors that are expected while scraping and are shown to the user rather than crashing a job."""


class ScrapeError(Exception):
    """Base class: a download, listing or extraction went wrong for a reason worth reporting."""
