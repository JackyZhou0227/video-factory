"""Database URL resolution and SQLAlchemy engine management."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool, Pool

_engines: dict[str, Engine] = {}
_engines_lock = threading.RLock()


def _application_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _application_config() -> Mapping[str, Any]:
    from app.core.config import app_config

    return app_config


def _database_config(config: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    source = _application_config() if config is None else config
    database = source.get("database") or {}
    return database if isinstance(database, Mapping) else {}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _non_negative_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default


def sqlite_url_for_path(path: str | Path) -> str:
    database_path = Path(path).expanduser().resolve()
    return f"sqlite:///{database_path.as_posix()}"


def _default_sqlite_url() -> str:
    return sqlite_url_for_path(_application_root() / "data" / "video_factory.db")


def get_database_url(config: Mapping[str, Any] | None = None) -> str:
    environment_url = os.getenv("DATABASE_URL", "").strip()
    if environment_url:
        return environment_url

    configured_url = str(_database_config(config).get("url") or "").strip()
    return configured_url or _default_sqlite_url()


def _enable_sqlite_foreign_keys(dbapi_connection: Any, connection_record: Any) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def create_engine_from_url(
    database_url: str,
    *,
    config: Mapping[str, Any] | None = None,
    poolclass: type[Pool] | None = None,
) -> Engine:
    url = make_url(database_url)
    engine_options: dict[str, Any] = {}

    if url.drivername.startswith("sqlite"):
        engine_options["connect_args"] = {"check_same_thread": False}
        engine_options["poolclass"] = NullPool
    else:
        database = _database_config(config)
        engine_options["pool_pre_ping"] = True
        if "pool_size" in database:
            engine_options["pool_size"] = _positive_int(database.get("pool_size"), 5)
        if "max_overflow" in database:
            engine_options["max_overflow"] = _non_negative_int(database.get("max_overflow"), 10)
        if "pool_timeout" in database:
            engine_options["pool_timeout"] = _positive_int(database.get("pool_timeout"), 30)

    if poolclass is not None:
        engine_options["poolclass"] = poolclass

    engine = create_engine(database_url, **engine_options)
    if url.drivername.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def get_engine(
    database_url: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> Engine:
    resolved_url = database_url or get_database_url(config)
    with _engines_lock:
        engine = _engines.get(resolved_url)
        if engine is None:
            engine = create_engine_from_url(resolved_url, config=config)
            _engines[resolved_url] = engine
        return engine


def dispose_engines() -> None:
    with _engines_lock:
        engines = list(_engines.values())
        _engines.clear()
    for engine in engines:
        engine.dispose()
    from app.db.session import clear_session_factories

    clear_session_factories()