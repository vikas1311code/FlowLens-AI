"""
tests/conftest.py
Shared pytest fixtures. The most important one is `temp_db`, which points
core.db at a throwaway SQLite file for the duration of a test — without it,
tests would read/write the real outputs/db/runs.sqlite3.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    import core.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_runs.sqlite3")
    db.init_db()
    yield db