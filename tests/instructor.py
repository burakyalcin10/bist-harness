"""Load the instructor's example scripts as modules so tests can compare against them.

The scripts are kept unmodified under ``reference/instructor``. They only run their
analysis under ``if __name__ == "__main__"``, so importing them is side-effect free apart
from a global ``warnings.filterwarnings("ignore")``, which is contained here.
"""

from __future__ import annotations

import importlib.util
import os
import warnings
from functools import lru_cache
from types import ModuleType

from .conftest import REPO_ROOT

SCENARIO3 = (
    REPO_ROOT / "reference" / "instructor" / "scenario3_technical_reversal_events_3_periods.py"
)


SCENARIO2 = REPO_ROOT / "reference" / "instructor" / "scenario2_thyao_weekday_patterns.py"


def _load(name: str, path) -> ModuleType:
    os.environ.setdefault("MPLBACKEND", "Agg")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def scenario3() -> ModuleType:
    return _load("instructor_scenario3", SCENARIO3)


@lru_cache(maxsize=1)
def scenario2() -> ModuleType:
    return _load("instructor_scenario2", SCENARIO2)
