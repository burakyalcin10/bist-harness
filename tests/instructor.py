"""Load the instructor's Scenario 3 script as a module so tests can compare against it.

The script is kept unmodified under ``reference/instructor``. It only runs its analysis
under ``if __name__ == "__main__"``, so importing it is side-effect free apart from a
global ``warnings.filterwarnings("ignore")``, which is contained here.
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


@lru_cache(maxsize=1)
def scenario3() -> ModuleType:
    os.environ.setdefault("MPLBACKEND", "Agg")
    spec = importlib.util.spec_from_file_location("instructor_scenario3", SCENARIO3)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        spec.loader.exec_module(module)
    return module
