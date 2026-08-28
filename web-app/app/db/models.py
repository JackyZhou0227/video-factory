"""SQLAlchemy mappings for the existing application tables."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, REAL, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')"),
        CheckConstraint("is_default IN (0, 1)"),
        {"comment": "系统用户"},
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
    __table_args__ = (
        Index("idx_subtitle_replacements_user", "user_id"),
        UniqueConstraint("user_id", "source"),
        {"comment": "用户字幕敏感词替换规则"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, nullable=False)
    user_id: Mapped[str] = mapped_column(Text, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    replacement: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    user: Mapped[User] = relationship()


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = {"comment": "全站共享模板"}

    id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(
        Text, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
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


# Keep the ORM metadata self-documenting as well as the database comments
# installed by Alembic.  This mapping is intentionally centralized so every
# existing column is covered without changing its runtime behavior.
_TABLE_COMMENTS = {
    "users": "系统用户",
    "sessions": "登录会话",
    "settings": "用户配置项",
    "subtitle_replacements": "用户字幕敏感词替换规则",
    "bgm_tracks": "用户背景音乐",
    "generation_tasks": "视频生成任务",
    "templates": "全站共享模板",
}
_COLUMN_COMMENTS = {
    "users": {"id": "用户唯一标识", "username": "登录用户名", "display_name": "显示名称", "role": "用户角色", "password_hash": "密码哈希", "password_salt": "密码盐值", "password_iterations": "密码哈希迭代次数", "is_default": "是否为默认用户", "created_at": "创建时间", "updated_at": "更新时间"},
    "sessions": {"id": "会话唯一标识", "user_id": "所属用户标识", "token_hash": "会话令牌哈希", "created_at": "创建时间", "expires_at": "过期时间", "revoked_at": "撤销时间"},
    "settings": {"id": "配置项 ID", "user_id": "所属用户标识", "namespace": "配置命名空间", "setting_name": "配置名称", "value": "配置值", "value_type": "配置值类型", "is_secret": "是否为敏感配置", "created_at": "创建时间", "updated_at": "更新时间"},
    "subtitle_replacements": {"id": "替换规则 ID", "user_id": "所属用户标识", "source": "需要替换的原词", "replacement": "字幕替换词", "created_at": "创建时间", "updated_at": "更新时间"},
    "bgm_tracks": {"id": "背景音乐唯一标识", "user_id": "所属用户标识", "name": "文件名称", "relative_path": "相对存储路径", "duration": "音频时长", "file_size": "文件大小", "created_at": "创建时间", "updated_at": "更新时间"},
    "generation_tasks": {"id": "任务唯一标识", "user_id": "所属用户标识", "creator_username": "创建者用户名", "creator_display_name": "创建者显示名称", "task_type": "任务类型", "generation_type": "生成类型", "requested_count": "请求生成数量", "success_count": "成功数量", "failed_count": "失败数量", "status": "任务状态", "progress": "任务进度", "message": "任务消息", "error": "错误信息", "storage_path": "任务存储路径", "extra_info_json": "任务扩展信息", "artifacts_json": "任务产物信息", "created_at": "创建时间", "started_at": "开始时间", "finished_at": "完成时间", "updated_at": "更新时间"},
    "templates": {"id": "模板唯一标识", "definition": "模板定义 JSON", "created_by": "创建模板的管理员", "created_at": "创建时间", "updated_at": "更新时间"},
}
for _table_name, _comment in _TABLE_COMMENTS.items():
    if _table_name in Base.metadata.tables:
        Base.metadata.tables[_table_name].comment = _comment
        for _column_name, _column_comment in _COLUMN_COMMENTS.get(_table_name, {}).items():
            Base.metadata.tables[_table_name].columns[_column_name].comment = _column_comment


__all__ = [
    "BgmTrack",
    "GenerationTask",
    "Session",
    "Setting",
    "SubtitleReplacement",
    "Template",
    "User",
]
