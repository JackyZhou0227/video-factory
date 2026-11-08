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
    "organizations",
    "voice_profiles",
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
            self.assertEqual(
                {column["name"] for column in inspector.get_columns("voice_profiles")},
                {
                    "id",
                    "user_id",
                    "name",
                    "language",
                    "ref_text",
                    "relative_path",
                    "file_size",
                    "created_at",
                    "updated_at",
                },
            )
            self.assertIn(
                "idx_voice_profiles_user_updated",
                {index["name"] for index in inspector.get_indexes("voice_profiles")},
            )
            voice_foreign_keys = inspector.get_foreign_keys("voice_profiles")
            self.assertEqual(voice_foreign_keys[0]["referred_table"], "users")
            self.assertEqual(voice_foreign_keys[0]["options"].get("ondelete"), "CASCADE")
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one(),
                    "0007",
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
                    "0007",
                )
            with engine.connect() as connection:
                self.assertEqual(
                    connection.execute(text("SELECT COUNT(*) FROM users")).scalar_one(),
                    1,
                )
        finally:
            engine.dispose()

    def test_comfyui_workflow_migration_renames_legacy_task_type_only(self):
        engine = create_engine_from_url(self.database_url)
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO users "
                        "(id, username, display_name, created_at, updated_at) "
                        "VALUES ('user-1', 'alice', 'Alice', '2026-08-23', '2026-08-23')"
                    )
                )
                connection.execute(
                    text(
                        "INSERT INTO generation_tasks "
                        "(id, user_id, task_type, generation_type, requested_count, status, "
                        "storage_path, extra_info_json, artifacts_json, created_at, updated_at) "
                        "VALUES "
                        "('legacy-dh', 'user-1', 'digital_human', 'video', 1, 'submitted', "
                        "'/output/tasks/digital_human/legacy-dh', "
                        "'{\"runninghub_task_id\":\"rh-123\"}', '[]', '2026-08-23', '2026-08-23'), "
                        "('voice-task', 'user-1', 'voice_generation', 'voice', 1, 'completed', "
                        "'/output/tasks/voice_generation/voice-task', '{}', '[]', '2026-08-23', '2026-08-23')"
                    )
                )
        finally:
            engine.dispose()

        command.stamp(self._config(), "0006")
        command.upgrade(self._config(), "head")

        engine = create_engine_from_url(self.database_url)
        try:
            with engine.connect() as connection:
                legacy = connection.execute(
                    text(
                        "SELECT task_type, storage_path, extra_info_json, status "
                        "FROM generation_tasks WHERE id = 'legacy-dh'"
                    )
                ).one()
                voice_type = connection.execute(
                    text("SELECT task_type FROM generation_tasks WHERE id = 'voice-task'")
                ).scalar_one()
            self.assertEqual(legacy.task_type, "comfyui_workflow")
            self.assertEqual(legacy.storage_path, "/output/tasks/digital_human/legacy-dh")
            self.assertEqual(
                legacy.extra_info_json,
                '{"runninghub_task_id":"rh-123"}',
            )
            self.assertEqual(legacy.status, "submitted")
            self.assertEqual(voice_type, "voice_generation")
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
