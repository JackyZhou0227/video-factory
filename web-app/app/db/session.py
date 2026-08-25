"""Short-lived SQLAlchemy session helpers."""

from __future__ import annotations

from contextlib import contextmanager
import threading
from typing import Any, Iterator, Mapping

from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from app.db.engine import get_database_url, get_engine

_session_factories: dict[str, sessionmaker[OrmSession]] = {}
_session_factories_lock = threading.RLock()


def create_session_factory(
    database_url: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> sessionmaker[OrmSession]:
    return sessionmaker(
        bind=get_engine(database_url, config=config),
        autoflush=False,
        expire_on_commit=False,
    )


def get_session_factory(
    database_url: str | None = None,
    *,
    config: Mapping[str, Any] | None = None,
) -> sessionmaker[OrmSession]:
    resolved_url = database_url or get_database_url(config)
    with _session_factories_lock:
        factory = _session_factories.get(resolved_url)
        if factory is None:
            factory = create_session_factory(resolved_url, config=config)
            _session_factories[resolved_url] = factory
        return factory


def clear_session_factories() -> None:
    with _session_factories_lock:
        _session_factories.clear()


@contextmanager
def session_scope(
    session_factory: sessionmaker[OrmSession] | None = None,
    *,
    database_url: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> Iterator[OrmSession]:
    factory = session_factory or create_session_factory(database_url, config=config)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()