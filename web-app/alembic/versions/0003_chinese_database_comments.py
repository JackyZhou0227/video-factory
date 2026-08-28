"""Document all application tables and columns in simplified Chinese."""

from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels = None
depends_on = None

TABLE_COMMENTS = {
    "users": "系统用户",
    "sessions": "登录会话",
    "settings": "用户配置项",
    "subtitle_replacements": "用户字幕敏感词替换规则",
    "bgm_tracks": "用户背景音乐",
    "generation_tasks": "视频生成任务",
    "templates": "全站共享模板",
    "alembic_version": "数据库迁移版本",
}

COLUMN_COMMENTS = {
    "users": {"id": "用户唯一标识", "username": "登录用户名", "display_name": "显示名称", "role": "用户角色", "password_hash": "密码哈希", "password_salt": "密码盐值", "password_iterations": "密码哈希迭代次数", "is_default": "是否为默认用户", "created_at": "创建时间", "updated_at": "更新时间"},
    "sessions": {"id": "会话唯一标识", "user_id": "所属用户标识", "token_hash": "会话令牌哈希", "created_at": "创建时间", "expires_at": "过期时间", "revoked_at": "撤销时间"},
    "settings": {"id": "配置项 ID", "user_id": "所属用户标识", "namespace": "配置命名空间", "setting_name": "配置名称", "value": "配置值", "value_type": "配置值类型", "is_secret": "是否为敏感配置", "created_at": "创建时间", "updated_at": "更新时间"},
    "subtitle_replacements": {"id": "替换规则 ID", "user_id": "所属用户标识", "source": "需要替换的原词", "replacement": "字幕替换词", "created_at": "创建时间", "updated_at": "更新时间"},
    "bgm_tracks": {"id": "背景音乐唯一标识", "user_id": "所属用户标识", "name": "文件名称", "relative_path": "相对存储路径", "duration": "音频时长", "file_size": "文件大小", "created_at": "创建时间", "updated_at": "更新时间"},
    "generation_tasks": {"id": "任务唯一标识", "user_id": "所属用户标识", "creator_username": "创建者用户名", "creator_display_name": "创建者显示名称", "task_type": "任务类型", "generation_type": "生成类型", "requested_count": "请求生成数量", "success_count": "成功数量", "failed_count": "失败数量", "status": "任务状态", "progress": "任务进度", "message": "任务消息", "error": "错误信息", "storage_path": "任务存储路径", "extra_info_json": "任务扩展信息", "artifacts_json": "任务产物信息", "created_at": "创建时间", "started_at": "开始时间", "finished_at": "完成时间", "updated_at": "更新时间"},
    "templates": {"id": "模板唯一标识", "definition": "模板定义 JSON", "created_by": "创建模板的管理员", "created_at": "创建时间", "updated_at": "更新时间"},
    "alembic_version": {"version_num": "数据库迁移版本号"},
}


def _quote(value: str) -> str:
    return value.replace("'", "''")


def upgrade() -> None:
    for table, comment in TABLE_COMMENTS.items():
        op.execute(f"COMMENT ON TABLE {table} IS '{_quote(comment)}'")
    for table, columns in COLUMN_COMMENTS.items():
        for column, comment in columns.items():
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS '{_quote(comment)}'")


def downgrade() -> None:
    for table, columns in COLUMN_COMMENTS.items():
        for column in columns:
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS NULL")
    for table in TABLE_COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
