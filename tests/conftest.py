"""Fixtures shared by the analysis and build tests: generate and analyse once per session."""
from __future__ import annotations

import pandas as pd
import pytest

from psim.analysis import analyse
from psim.generate import generate


@pytest.fixture(scope="session")
def events() -> pd.DataFrame:
    return generate()


@pytest.fixture(scope="session")
def analysis(events: pd.DataFrame) -> dict:
    return analyse(events)
