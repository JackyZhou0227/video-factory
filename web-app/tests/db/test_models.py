from __future__ import annotations

import json
import unittest

from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.engine import create_engine_from_url
from app.db.models import (
    BgmTrack,
    GenerationTask,
    Session as DbSession,
    Setting,
    SubtitleReplacement,
    User,
)
from app.db.engine import get_database_url
from app.db.session import get_session_factory, session_scope
from app.services import auth_store, settings_store, task_store
from tests.pg_test_utils import TEST_DATABASE_URL


TABLE_NAMES = {
    "users",
    "sessions",
    "settings",
    "subtitle_replacements",
    "bgm_tracks",
    "generation_tasks",
}
CREATED_AT = "2026-08-23T00:00:00+00:00"
EXPIRES_AT = "2026-09-22T00:00:00+00:00"


class DbModelsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine_from_url(TEST_DATABASE_URL)
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()

    @staticmethod
    def _user(user_id: str = "user-1", username: str = "alice") -> User:
        return User(
            id=user_id,
            username=username,
            display_name="Alice",
            role="user",
            password_hash="password-hash",
            password_salt="password-salt",
            password_iterations=390000,
            is_default=0,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )

    @staticmethod
    def _session(
        user_id: str = "user-1",
        session_id: str = "session-1",
        token_hash: str = "token-hash-1",
    ) -> DbSession:
        return DbSession(
            id=session_id,
            user_id=user_id,
            token_hash=token_hash,
            created_at=CREATED_AT,
            expires_at=EXPIRES_AT,
            revoked_at=None,
        )

    @staticmethod
    def _setting(
        user_id: str = "user-1",
        setting_name: str = "model",
        value: str = "seed-model",
    ) -> Setting:
        return Setting(
            user_id=user_id,
            namespace="llm",
            setting_name=setting_name,
            value=value,
            value_type="string",
            is_secret=0,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )

    @staticmethod
    def _subtitle_replacement(
        source: str = "医生",
        replacement: str = "yi生",
    ) -> SubtitleReplacement:
        return SubtitleReplacement(
            source=source,
            replacement=replacement,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )

    @staticmethod
    def _bgm_track(
        user_id: str = "user-1",
        track_id: str = "bgm-1",
    ) -> BgmTrack:
        return BgmTrack(
            id=track_id,
            user_id=user_id,
            name="Quiet Intro",
            relative_path="bgm/user-1/quiet-intro.mp3",
            duration=12.5,
            file_size=4096,
            created_at=CREATED_AT,
            updated_at=CREATED_AT,
        )

    @staticmethod
    def _generation_task(
        user_id: str = "user-1",
        task_id: str = "00000000-0000-0000-0000-000000000001",
    ) -> GenerationTask:
        return GenerationTask(
            id=task_id,
            user_id=user_id,
            creator_username="alice",
            creator_display_name="Alice",
            task_type="voice_generation",
            generation_type="voice",
            requested_count=1,
            success_count=0,
            failed_count=0,
            status="pending",
            progress=0,
            message="任务已创建",
            error=None,
            storage_path="tasks/00000000-0000-0000-0000-000000000001",
            extra_info_json=json.dumps(
                {"provider": "edge-tts", "nested": {"enabled": True}},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            artifacts_json=json.dumps(
                [{"id": "artifact-1", "status": "completed"}],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            created_at=CREATED_AT,
            started_at=None,
            finished_at=None,
            updated_at=CREATED_AT,
        )

    def test_store_sessions_share_database_url_and_engine(self):
        database_url = TEST_DATABASE_URL
        settings_factory = get_session_factory(database_url)
        auth_factory = get_session_factory(database_url)
        task_factory = get_session_factory(database_url)

        self.assertIs(settings_factory, auth_factory)
        self.assertIs(auth_factory, task_factory)
        self.assertIs(settings_factory.kw["bind"], auth_factory.kw["bind"])
        self.assertEqual(get_database_url({"database": {"url": database_url}}), database_url)

    def test_create_all_inserts_and_queries_all_models(self):
        self.assertEqual(set(inspect(self.engine).get_table_names()), TABLE_NAMES)

        user = self._user()
        auth_session = self._session()
        setting = self._setting()
        replacement = self._subtitle_replacement()
        bgm_track = self._bgm_track()
        generation_task = self._generation_task()
        user_id = user.id
        session_id = auth_session.id
        bgm_track_id = bgm_track.id
        generation_task_id = generation_task.id

        with session_scope(self.session_factory) as db_session:
            db_session.add(user)
            db_session.flush()
            db_session.add_all(
                [auth_session, setting, replacement, bgm_track, generation_task]
            )
            db_session.flush()
            setting_id = setting.id
            replacement_id = replacement.id

        with session_scope(self.session_factory) as db_session:
            loaded_user = db_session.scalar(select(User).where(User.id == user_id))
            loaded_session = db_session.scalar(
                select(DbSession).where(DbSession.id == session_id)
            )
            loaded_setting = db_session.scalar(
                select(Setting).where(Setting.id == setting_id)
            )
            loaded_replacement = db_session.scalar(
                select(SubtitleReplacement).where(
                    SubtitleReplacement.id == replacement_id
                )
            )
            loaded_bgm_track = db_session.scalar(
                select(BgmTrack).where(BgmTrack.id == bgm_track_id)
            )
            loaded_generation_task = db_session.scalar(
                select(GenerationTask).where(GenerationTask.id == generation_task_id)
            )

            self.assertEqual(loaded_user.username, "alice")
            self.assertEqual(loaded_session.token_hash, "token-hash-1")
            self.assertEqual(loaded_setting.value, "seed-model")
            self.assertEqual(loaded_replacement.replacement, "yi生")
            self.assertEqual(loaded_bgm_track.name, "Quiet Intro")

            self.assertIsInstance(loaded_generation_task.extra_info_json, str)
            self.assertEqual(
                json.loads(loaded_generation_task.extra_info_json),
                {"provider": "edge-tts", "nested": {"enabled": True}},
            )
            self.assertIsInstance(loaded_generation_task.artifacts_json, str)
            self.assertEqual(
                json.loads(loaded_generation_task.artifacts_json),
                [{"id": "artifact-1", "status": "completed"}],
            )

    def test_foreign_keys_reject_orphan_rows(self):
        orphan_rows = (
            (
                "sessions.user_id",
                self._session(
                    user_id="missing-user",
                    session_id="orphan-session",
                    token_hash="orphan-token",
                ),
            ),
            (
                "settings.user_id",
                self._setting(user_id="missing-user", setting_name="orphan"),
            ),
            (
                "bgm_tracks.user_id",
                self._bgm_track(user_id="missing-user", track_id="orphan-bgm"),
            ),
            (
                "generation_tasks.user_id",
                self._generation_task(
                    user_id="missing-user",
                    task_id="00000000-0000-0000-0000-000000000002",
                ),
            ),
        )

        for constraint_name, orphan_row in orphan_rows:
            with self.subTest(constraint=constraint_name):
                with self.assertRaises(IntegrityError):
                    with session_scope(self.session_factory) as db_session:
                        db_session.add(orphan_row)
                        db_session.flush()

    def test_unique_constraints_reject_duplicate_values(self):
        user = self._user()
        auth_session = self._session()
        setting = self._setting()
        replacement = self._subtitle_replacement()
        bgm_track = self._bgm_track()

        with session_scope(self.session_factory) as db_session:
            db_session.add(user)
            db_session.flush()
            db_session.add_all([auth_session, setting, replacement, bgm_track])

        duplicate_rows = (
            (
                "users.username",
                self._user(user_id="user-2", username="alice"),
            ),
            (
                "sessions.token_hash",
                self._session(
                    session_id="session-2",
                    token_hash="token-hash-1",
                ),
            ),
            (
                "settings.user_id_namespace_setting_name",
                self._setting(setting_name="model", value="other-model"),
            ),
            (
                "subtitle_replacements.source",
                self._subtitle_replacement(replacement="other"),
            ),
            (
                "bgm_tracks.id",
                self._bgm_track(track_id="bgm-1"),
            ),
        )

        for constraint_name, duplicate_row in duplicate_rows:
            with self.subTest(constraint=constraint_name):
                with self.assertRaises(IntegrityError):
                    with session_scope(self.session_factory) as db_session:
                        db_session.add(duplicate_row)
                        db_session.flush()


if __name__ == "__main__":
    unittest.main()
