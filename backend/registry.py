"""The plugin mechanism behind fetchers, connectors, extractors and analyzers.

Each of those packages owns one `Registry`. A plugin is a class with a unique
`name`, decorated with `@<registry>.register`. `autodiscover()` imports every
module in the package, so dropping a new file in the folder is all it takes.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import asdict, dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class Field:
    """One option a plugin understands.

    The same declaration feeds three places: the recipe editor in the dashboard,
    the tool schema Claude fills in, and the documentation in Claude's prompt.
    """

    key: str
    label: str
    help: str = ""
    type: str = "text"  # text | number | select
    choices: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        return {**asdict(self), "choices": list(self.choices)}


class UnknownPlugin(KeyError):
    pass


class Registry(Generic[T]):
    def __init__(self, kind: str):
        self.kind = kind
        self._classes: dict[str, type[T]] = {}
        self._instances: dict[str, T] = {}

    def register(self, cls: type[T]) -> type[T]:
        name = getattr(cls, "name", "")
        if not name:
            raise ValueError(f"{cls.__name__} needs a `name` to be registered as a {self.kind}")
        self._classes[name] = cls
        self._instances.pop(name, None)
        return cls

    def get(self, name: str) -> T:
        """The shared instance of a plugin."""
        if name not in self._classes:
            raise UnknownPlugin(f"Unknown {self.kind} '{name}'. Available: {', '.join(self.names())}")
        if name not in self._instances:
            self._instances[name] = self._classes[name]()
        return self._instances[name]

    def names(self) -> list[str]:
        return list(self._classes)

    def all(self) -> list[T]:
        return [self.get(name) for name in self._classes]

    def describe(self) -> list[dict]:
        described = []
        for plugin in self.all():
            entry = {
                "name": plugin.name,
                "label": getattr(plugin, "label", plugin.name),
                "description": getattr(plugin, "description", ""),
                "fields": [f.as_dict() for f in getattr(plugin, "fields", [])],
            }
            for extra in ("requires_ai",):
                if hasattr(plugin, extra):
                    entry[extra] = getattr(plugin, extra)
            described.append(entry)
        return described


def autodiscover(package_name: str, package_path) -> None:
    """Import every plugin module of a package (skips `base` and `_private` modules)."""
    for module in pkgutil.iter_modules(package_path):
        if module.name == "base" or module.name.startswith("_"):
            continue
        importlib.import_module(f"{package_name}.{module.name}")
