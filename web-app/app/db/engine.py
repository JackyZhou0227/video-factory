"""Database URL resolution and SQLAlchemy engine management."""

from __future__ import annotations

import threading
from typing import Any, Mapping

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import Pool

_engines: dict[str, Engine] = {}
_engines_lock = threading.RLock()


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


def get_database_url(config: Mapping[str, Any] | None = None) -> str:
    configured_url = str(_database_config(config).get("url") or "").strip()
    if not configured_url:
        raise RuntimeError(
            "Video Factory requires PostgreSQL; configure database.url "
            "in config.yaml with a postgresql+psycopg URL."
        )
    return configured_url


def require_postgresql_url(config: Mapping[str, Any] | None = None) -> str:
    """Resolve and validate the PostgreSQL URL used by the application."""

    database_url = get_database_url(config)
    if not make_url(database_url).drivername.startswith("postgresql"):
        raise RuntimeError("Video Factory requires a PostgreSQL database URL.")
    return database_url


def create_engine_from_url(
    database_url: str,
    *,
    config: Mapping[str, Any] | None = None,
    poolclass: type[Pool] | None = None,
) -> Engine:
    url = make_url(database_url)
    engine_options: dict[str, Any] = {}
    if not url.drivername.startswith("postgresql"):
        raise RuntimeError("Video Factory requires a PostgreSQL database URL.")

    database = _database_config(config)
    engine_options["pool_pre_ping"] = True
    if poolclass is None:
        if "pool_size" in database:
            engine_options["pool_size"] = _positive_int(database.get("pool_size"), 5)
        if "max_overflow" in database:
            engine_options["max_overflow"] = _non_negative_int(database.get("max_overflow"), 10)
        if "pool_timeout" in database:
            engine_options["pool_timeout"] = _positive_int(database.get("pool_timeout"), 30)

    if poolclass is not None:
        engine_options["poolclass"] = poolclass

    return create_engine(database_url, **engine_options)


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
