"""Add-ons: parts of the platform that live in a folder of their own and can be taken out again.

An add-on is a package in this folder (`backend/addons/<name>/`). On start the platform imports each one and
uses these names from it, when the add-on has them:

* `router` - an `APIRouter` with the add-on's routes, mounted next to the platform's own;
* `init()` - called once on start, after the database is ready (for the add-on's own tables);
* `after_scrape(job)` - called at the end of every scrape, after the new items are embedded. It must be free
  (no Claude) and quick. What it returns is kept in the scrape's result, under the add-on's name;
* `meta()` - what the dashboard needs to know about it, sent as `meta.addons.<name>`. The dashboard shows an
  add-on only when its name is there, so a dashboard built with the add-on still works with a platform that
  was not restarted since, or that no longer has it.

Deleting an add-on's folder removes it: nothing outside it imports it. Its tables stay in the library, unused.
An add-on that fails to import or to start is left out, with the reason in `failed` and on the console, and the
platform starts without it.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

log = logging.getLogger(__name__)

loaded: dict[str, ModuleType] = {}
failed: dict[str, str] = {}
_scanned = False


def discover() -> dict[str, ModuleType]:
    """The add-ons, imported once."""
    global _scanned
    if not _scanned:
        _scanned = True
        for found in pkgutil.iter_modules(__path__):
            if found.name.startswith("_"):
                continue
            try:
                loaded[found.name] = importlib.import_module(f"{__name__}.{found.name}")
            except Exception as error:  # a broken add-on must not keep the platform from starting
                _leave_out(found.name, error)
    return loaded


def _leave_out(name: str, error: Exception) -> None:
    loaded.pop(name, None)
    failed[name] = f"{type(error).__name__}: {error}"
    log.warning("The add-on '%s' was left out: %s", name, failed[name])


def routers() -> list:
    return [module.router for module in discover().values() if getattr(module, "router", None) is not None]


def init() -> None:
    for name, module in list(discover().items()):
        if hasattr(module, "init"):
            try:
                module.init()
            except Exception as error:  # its routes stay mounted, but the dashboard no longer offers it
                _leave_out(name, error)


def after_scrape(job) -> dict:
    """The free steps the add-ons take after a scrape. One that fails is logged; the scrape is not failed for it,
    because what was scraped is stored."""
    results = {}
    for name, module in discover().items():
        hook = getattr(module, "after_scrape", None)
        if hook is None:
            continue
        try:
            result = hook(job)
        except Exception as error:
            job.log(f"{name}: {type(error).__name__}: {error}", "warn")
            continue
        if result:
            results[name] = result
    return results


def meta() -> dict:
    return {name: (module.meta() if hasattr(module, "meta") else {}) for name, module in discover().items()}
