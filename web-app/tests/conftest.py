from __future__ import annotations

import pytest

from app.core.config import app_config
from app.db.engine import dispose_engines
from tests.pg_test_utils import TEST_DATABASE_URL, truncate_app_tables


def pytest_sessionstart(session: pytest.Session) -> None:
    del session
    app_config.setdefault("database", {})["url"] = TEST_DATABASE_URL
    truncate_app_tables()


@pytest.fixture(autouse=True)
def isolate_database_for_tests(monkeypatch: pytest.MonkeyPatch):
    """Use an isolated PostgreSQL database and reset it before every test."""

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setitem(app_config.setdefault("database", {}), "url", TEST_DATABASE_URL)
    truncate_app_tables()
    yield
    dispose_engines()
