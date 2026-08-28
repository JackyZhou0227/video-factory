from __future__ import annotations

from pathlib import Path
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.db.base import Base
from app.db.engine import create_engine_from_url
from tests.pg_test_utils import TEST_DATABASE_URL, drop_database_objects, reset_public_schema


TABLE_NAMES = {
    "users",
    "sessions",
    "settings",
    "subtitle_replacements",
    "bgm_tracks",
    "generation_tasks",
    "templates",
}


class AlembicMigrationTests(unittest.TestCase):
    def setUp(self):
        drop_database_objects()
        self.database_url = TEST_DATABASE_URL
        self.config_path = Path(__file__).resolve().parents[2] / "alembic.ini"

    def tearDown(self):
        reset_public_schema()

    def _config(self) -> Config:
        return Config(str(self.config_path))

    def test_upgrade_head_creates_baseline_schema(self):
        command.upgrade(self._config(), "head")

        engine = create_engine_from_url(self.database_url)
        try:
            inspector = inspect(engine)
            self.assertEqual(
                set(inspector.get_table_names()),
                TABLE_NAMES | {"alembic_version"},
            )
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    "0003",
                )
        finally:
            engine.dispose()

    def test_existing_schema_can_be_stamped_and_checked_without_data_changes(self):
        engine = create_engine_from_url(self.database_url)
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "ALTER TABLE bgm_tracks "
                        "ADD COLUMN loudness REAL NOT NULL DEFAULT 0"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, username, display_name, created_at, updated_at) "
                        "VALUES (:id, :username, :display_name, :created_at, :updated_at)"
                    ),
                    {
                        "id": "user-1",
                        "username": "alice",
                        "display_name": "Alice",
                        "created_at": "2026-08-23T00:00:00+00:00",
                        "updated_at": "2026-08-23T00:00:00+00:00",
                    },
                )
            before = {
                table: tuple(column["name"] for column in inspect(engine).get_columns(table))
                for table in TABLE_NAMES
            }
        finally:
            engine.dispose()

        command.stamp(self._config(), "head")
        command.check(self._config())

        engine = create_engine_from_url(self.database_url)
        try:
            inspector = inspect(engine)
            after = {
                table: tuple(column["name"] for column in inspector.get_columns(table))
                for table in TABLE_NAMES
            }
            self.assertEqual(after, before)
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    "0003",
                )
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one(),
                    1,
                )
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
