"""Add database-backed personal voice profiles."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voice_profiles",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, comment="音色档案唯一标识"),
        sa.Column("user_id", sa.Text(), nullable=False, comment="所属用户标识"),
        sa.Column("name", sa.Text(), nullable=False, comment="音色名称"),
        sa.Column("language", sa.Text(), nullable=False, comment="参考音频语言"),
        sa.Column("ref_text", sa.Text(), nullable=False, comment="参考音频台词"),
        sa.Column("relative_path", sa.Text(), nullable=False, unique=True, comment="参考音频相对路径"),
        sa.Column("file_size", sa.Integer(), nullable=False, comment="参考音频文件大小"),
        sa.Column("created_at", sa.Text(), nullable=False, comment="创建时间"),
        sa.Column("updated_at", sa.Text(), nullable=False, comment="更新时间"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        comment="用户个人音色档案",
    )
    op.create_index(
        "idx_voice_profiles_user_updated",
        "voice_profiles",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_voice_profiles_user_updated", table_name="voice_profiles")
    op.drop_table("voice_profiles")
