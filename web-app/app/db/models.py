"""SQLAlchemy mappings for the existing application tables."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, REAL, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')"),
        CheckConstraint("is_default IN (0, 1)"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'user'"))
    password_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    password_salt: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    password_iterations: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    is_default: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    settings: Mapped[list["Setting"]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    bgm_tracks: Mapped[list["BgmTrack"]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    generation_tasks: Mapped[list["GenerationTask"]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_token_hash", "token_hash"),
        Index("idx_sessions_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)
    revoked_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class Setting(Base):
    __tablename__ = "settings"
    __table_args__ = (
        Index("idx_settings_user_namespace", "user_id", "namespace"),
        UniqueConstraint("user_id", "namespace", "setting_name"),
        CheckConstraint("is_secret IN (0, 1)"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    namespace: Mapped[str] = mapped_column(Text, nullable=False)
    setting_name: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    value_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'string'"))
    is_secret: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship(back_populates="settings")


class SubtitleReplacement(Base):
    __tablename__ = "subtitle_replacements"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    replacement: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class BgmTrack(Base):
    __tablename__ = "bgm_tracks"
    __table_args__ = (Index("idx_bgm_tracks_user", "user_id"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    relative_path: Mapped[str] = mapped_column(Text, nullable=False)
    duration: Mapped[float] = mapped_column(REAL, nullable=False, server_default=text("0"))
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship(back_populates="bgm_tracks")


class GenerationTask(Base):
    __tablename__ = "generation_tasks"
    __table_args__ = (
        Index("idx_generation_tasks_user_created", "user_id", "created_at"),
        Index("idx_generation_tasks_user_type", "user_id", "task_type", "generation_type"),
        Index("idx_generation_tasks_status", "user_id", "status"),
        CheckConstraint("requested_count >= 1"),
        CheckConstraint("success_count >= 0"),
        CheckConstraint("failed_count >= 0"),
        CheckConstraint("progress >= 0 AND progress <= 100"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    user_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    creator_username: Mapped[str] = mapped_column(Text, nullable=False)
    creator_display_name: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(Text, nullable=False)
    generation_type: Mapped[str] = mapped_column(Text, nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    message: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    extra_info_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'{}'"))
    artifacts_json: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'[]'"))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship(back_populates="generation_tasks")


__all__ = [
    "BgmTrack",
    "GenerationTask",
    "Session",
    "Setting",
    "SubtitleReplacement",
    "User",
]
