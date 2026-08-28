from __future__ import annotations

import json
from typing import Any
from pathlib import Path

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.engine import make_url

from app.core.config import app_config
from app.db.base import Base
from app.db.engine import create_engine_from_url, dispose_engines
from app.db.models import GenerationTask, Session as DbSession, Template, User
from app.services.template_registry import parse_template_json
from app.services import settings_store

APP_TABLES = (
    "users",
    "sessions",
    "settings",
    "subtitle_replacements",
    "bgm_tracks",
    "generation_tasks",
    "templates",
)

TEST_DATABASE_URL = str(
    make_url(str(app_config["database"]["url"]))
    .set(database="video_factory_test")
    .render_as_string(hide_password=False)
)


def create_schema() -> None:
    engine = create_engine_from_url(TEST_DATABASE_URL)
    try:
        Base.metadata.create_all(engine)
    finally:
        engine.dispose()


def reset_public_schema() -> None:
    drop_database_objects()
    create_schema()


def drop_database_objects() -> None:
    dispose_engines()
    engine = create_engine_from_url(TEST_DATABASE_URL)
    try:
        Base.metadata.drop_all(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        engine.dispose()
    dispose_engines()


def truncate_app_tables() -> None:
    create_schema()
    engine = create_engine_from_url(TEST_DATABASE_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE TABLE users, sessions, settings, subtitle_replacements, bgm_tracks, generation_tasks, templates RESTART IDENTITY CASCADE"))
    finally:
        engine.dispose()
    dispose_engines()
    ensure_test_templates()


def ensure_test_templates() -> None:
    """Restore migration seed templates after per-test table truncation."""
    builtin_root = Path(__file__).resolve().parents[1] / "app" / "templates" / "builtin"
    with settings_store._orm_session() as session:
        for path in sorted(builtin_root.glob("*.json")):
            definition = parse_template_json(path.read_bytes())
            if session.get(Template, definition.id) is None:
                now = settings_store._now_iso()
                session.add(Template(
                    id=definition.id,
                    definition=definition.model_dump(mode="json", exclude_none=True),
                    created_by=None,
                    created_at=now,
                    updated_at=now,
                ))


def ensure_test_user(
    user_id: str,
    *,
    username: str | None = None,
    display_name: str | None = None,
) -> None:
    now = settings_store._now_iso()
    normalized_username = username or user_id
    normalized_display_name = display_name or normalized_username
    with settings_store._orm_session() as session:
        user = session.get(User, user_id)
        if user is None:
            session.add(
                User(
                    id=user_id,
                    username=normalized_username,
                    display_name=normalized_display_name,
                    role="user",
                    password_hash="",
                    password_salt="",
                    password_iterations=0,
                    is_default=0,
                    created_at=now,
                    updated_at=now,
                )
            )
            return
        user.username = normalized_username
        user.display_name = normalized_display_name
        user.updated_at = now


def column_names(table_name: str) -> set[str]:
    engine = create_engine_from_url(TEST_DATABASE_URL)
    try:
        return {column["name"] for column in inspect(engine).get_columns(table_name)}
    finally:
        engine.dispose()


def index_names(table_name: str) -> set[str]:
    engine = create_engine_from_url(TEST_DATABASE_URL)
    try:
        return {index["name"] for index in inspect(engine).get_indexes(table_name)}
    finally:
        engine.dispose()


def table_names() -> set[str]:
    engine = create_engine_from_url(TEST_DATABASE_URL)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def set_task_artifacts(task_id: str, artifacts: list[dict[str, Any]]) -> None:
    with settings_store._orm_session() as session:
        session.execute(
            update(GenerationTask)
            .where(GenerationTask.id == task_id)
            .values(artifacts_json=json.dumps(artifacts, ensure_ascii=False))
        )


def task_extra_info_json(task_id: str) -> str:
    with settings_store._orm_session() as session:
        return str(
            session.scalar(
                select(GenerationTask.extra_info_json).where(
                    GenerationTask.id == task_id
                )
            )
        )


def set_session_expires_at(token_hash: str, expires_at: str) -> None:
    with settings_store._orm_session() as session:
        session.execute(
            update(DbSession)
            .where(DbSession.token_hash == token_hash)
            .values(expires_at=expires_at)
        )


def count_sessions(user_id: str) -> int:
    with settings_store._orm_session() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(DbSession)
                .where(DbSession.user_id == user_id)
            )
            or 0
        )
