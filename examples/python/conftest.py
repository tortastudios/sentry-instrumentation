"""Makes the reference examples importable as `yourapp.*` so the gates run.

The example modules import each other through the paths they are meant
to be dropped into (`yourapp.observability`, `yourapp.shared.metrics`,
…). This conftest builds that package in memory from the files in this
directory, so `pytest examples/python` exercises the real example code
without a scaffolded project.

Not part of the drop-in set — your project has a real `yourapp`.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent


def _package(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []  # mark as a package
    sys.modules[name] = module
    return module


def _load(name: str, filename: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    parent, _, child = name.rpartition(".")
    setattr(sys.modules[parent], child, module)
    return module


@dataclass
class Settings:
    sentry_dsn: str = ""
    environment: str = "test"


def _build() -> None:
    if "yourapp" in sys.modules:
        return
    yourapp = _package("yourapp")
    yourapp.shared = _package("yourapp.shared")  # type: ignore[attr-defined]

    config = types.ModuleType("yourapp.config")
    config.Settings = Settings  # type: ignore[attr-defined]
    config.get_settings = lambda: Settings()  # type: ignore[attr-defined]
    sys.modules["yourapp.config"] = config
    yourapp.config = config  # type: ignore[attr-defined]

    _load("yourapp.shared.failure_taxonomy", "failure_taxonomy.py")
    _load("yourapp.shared.metrics", "metric_def.py")
    _load("yourapp.shared.metric_tags", "metric_tags.py")
    _load("yourapp.observability", "emission_module.py")


_build()
