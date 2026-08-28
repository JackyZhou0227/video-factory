"""Add user-scoped subtitle rules and database-backed shared templates."""

from datetime import datetime, timezone
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels = None
depends_on = None


# These are deliberately embedded in the migration: deployment must not depend
# on the source tree's template files being present.
SEED_TEMPLATES = (
    {
        "schema_version": 1,
        "template_version": 1,
        "id": "doctor-intro",
        "name": "医生介绍",
        "description": "组合医生形象和医院环境，批量制作专业介绍视频。",
        "content_fields": [
            {"key": "doctor-name", "label": "医生姓名", "input_type": "text", "required": True, "placeholder": "例如：张医生", "max_length": 100},
            {"key": "hospital", "label": "所在医院", "input_type": "text", "required": True, "placeholder": "例如：北京协和医院", "max_length": 200},
            {"key": "department", "label": "科室", "input_type": "text", "required": True, "placeholder": "例如：心内科", "max_length": 100},
            {"key": "specialty", "label": "专业特长", "input_type": "text", "required": True, "placeholder": "例如：冠心病、高血压诊疗", "max_length": 500},
        ],
        "material_requirements": [
            {"key": "doctor-image", "label": "医生形象照", "description": "清晰展示医生形象的照片。", "media_type": "image", "min_count": 1, "max_count": 3},
            {"key": "hospital-scene", "label": "医院环境", "description": "展示医院或科室环境的视频。", "media_type": "video", "min_count": 1, "max_count": 3},
        ],
        "script_generation": {
            "system_prompt": "你是专业、克制的中文短视频文案编导，必须严格遵守事实边界和输出格式。",
            "prompt_template": "你是一位专业的中文短视频口播文案撰写专家。\n\n【人物信息】\n{{content_context}}\n\n【可用画面】\n{{material_context}}\n\n【任务】\n生成 {{candidate_count}} 条彼此明显不同的短视频口播文案。\n每条控制在 50-100 个汉字，语言自然、适合直接配音，不要标题、编号或解释。\n突出医生的专业能力、医院背景和可信赖感，避免医疗效果承诺和夸张用语。\n\n【输出格式】\n{{response_contract}}",
            "rewrite_prompt_template": "你是一位专业的中文短视频口播文案撰写专家。\n\n【人物信息】\n{{content_context}}\n\n【可用画面】\n{{material_context}}\n\n【当前候选】\n{{original_script}}\n\n【任务】\n保留人物事实，换一个切入角度和表达方式，将当前候选完整重写为 {{candidate_count}} 条文案。\n每条控制在 50-100 个汉字，语言自然、适合直接配音，不要标题、编号或解释。\n突出医生的专业能力、医院背景和可信赖感，避免医疗效果承诺和夸张用语。\n\n【输出格式】\n{{response_contract}}",
            "response_format": "plain_scripts_v1", "default_candidate_count": 3, "temperature": 0.75, "max_tokens": 2400,
        },
        "production": {"pipeline_id": "generic_concat_v1", "default_ratio": "9:16", "default_batch_size": 5, "max_batch_size": 50},
    },
    {
        "schema_version": 1,
        "template_version": 1,
        "id": "zhongyi-xunfang",
        "name": "中医寻访",
        "description": "用问诊和诊所画面生成真实、有温度的寻访口播。",
        "content_fields": [
            {"key": "address", "label": "医生地址", "input_type": "text", "required": True, "placeholder": "例如：湖北阳新的一条老街", "max_length": 200},
            {"key": "name", "label": "医生称呼", "input_type": "text", "required": True, "placeholder": "例如：马医生", "max_length": 100},
            {"key": "specialty", "label": "医生专长", "input_type": "text", "required": True, "placeholder": "例如：中医内科、慢性病调理", "max_length": 500},
            {"key": "feature", "label": "医生特点", "input_type": "text", "required": False, "placeholder": "例如：三代中医世家", "max_length": 1000},
        ],
        "material_requirements": [
            {"key": "doctor-scene", "label": "中医师问诊画面", "description": "能够清楚展示医生问诊过程的视频。", "media_type": "video", "min_count": 1, "max_count": 5},
            {"key": "clinic-scene", "label": "诊所环境画面", "description": "展示诊所空间、陈设或环境细节的视频。", "media_type": "video", "min_count": 1, "max_count": 3},
        ],
        "script_generation": {
            "system_prompt": "你是专业、克制的中文短视频文案编导，必须严格遵守事实边界和输出格式。",
            "prompt_template": "请根据用户提供的信息，生成 {{candidate_count}} 条中医寻访口播文案。\n\n用户信息：\n{{content_context}}\n\n可用画面：\n{{material_context}}\n\n输出格式：\n{{response_contract}}",
            "rewrite_prompt_template": "请结合下列信息重写当前候选为 {{candidate_count}} 条中医寻访口播文案。\n\n用户信息：\n{{content_context}}\n\n可用画面：\n{{material_context}}\n\n当前候选：\n{{original_script}}\n\n输出格式：\n{{response_contract}}",
            "response_format": "segmented_scripts_v1", "default_candidate_count": 3, "temperature": 0.75, "max_tokens": 2400,
        },
        "production": {"pipeline_id": "zhongyi_visit_v1", "default_ratio": "9:16", "default_batch_size": 5, "max_batch_size": 50},
    },
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Video Factory migrations require PostgreSQL")
    if bind.execute(sa.text("SELECT COUNT(*) FROM subtitle_replacements")).scalar_one():
        raise RuntimeError("无法自动迁移已有全局敏感词，请先人工分配 user_id")

    op.add_column("subtitle_replacements", sa.Column("user_id", sa.Text(), nullable=True))
    op.drop_constraint("subtitle_replacements_source_key", "subtitle_replacements", type_="unique")
    # The current production database has no legacy rows. Keep the explicit
    # check above so a future non-empty legacy table cannot be misassigned.
    op.alter_column("subtitle_replacements", "user_id", nullable=False)
    op.create_foreign_key("fk_subtitle_replacements_user", "subtitle_replacements", "users", ["user_id"], ["id"], ondelete="CASCADE")
    op.create_index("idx_subtitle_replacements_user", "subtitle_replacements", ["user_id"])
    op.create_unique_constraint("uq_subtitle_replacements_user_source", "subtitle_replacements", ["user_id", "source"])

    op.create_table(
        "templates",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("definition", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    now = datetime.now(timezone.utc).isoformat()
    for definition in SEED_TEMPLATES:
        bind.execute(
            sa.text("INSERT INTO templates (id, definition, created_by, created_at, updated_at) VALUES (:id, CAST(:definition AS jsonb), NULL, :created_at, :updated_at)"),
            {"id": definition["id"], "definition": json.dumps(definition, ensure_ascii=False), "created_at": now, "updated_at": now},
        )


def downgrade() -> None:
    op.drop_table("templates")
    op.drop_constraint("uq_subtitle_replacements_user_source", "subtitle_replacements", type_="unique")
    op.drop_index("idx_subtitle_replacements_user", table_name="subtitle_replacements")
    op.drop_constraint("fk_subtitle_replacements_user", "subtitle_replacements", type_="foreignkey")
    op.drop_column("subtitle_replacements", "user_id")
    op.create_unique_constraint("subtitle_replacements_source_key", "subtitle_replacements", ["source"])
