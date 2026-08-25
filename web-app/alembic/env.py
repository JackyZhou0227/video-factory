from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy.pool import NullPool

from app.db import models as _models
from app.db.base import Base
from app.db.engine import create_engine_from_url, get_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return get_database_url()


def _include_object(
    object_: object,
    name: str,
    type_: str,
    reflected: bool,
    compare_to: object | None,
) -> bool:
    if type_ != "column":
        return True
    if getattr(object_, "primary_key", False):
        return False
    if not reflected:
        return True
    if name == "loudness" and compare_to is None:
        table = getattr(object_, "table", None)
        return getattr(table, "name", None) != "bgm_tracks"
    return True


def _configure_context(**options: object) -> None:
    context.configure(
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=_include_object,
        **options,
    )


def run_migrations_offline() -> None:
    _configure_context(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    database_url = _database_url()
    connectable = create_engine_from_url(database_url, poolclass=NullPool)
    try:
        with connectable.connect() as connection:
            _configure_context(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
