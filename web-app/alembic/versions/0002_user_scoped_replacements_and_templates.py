"""Add user-scoped subtitle rules and database-backed shared templates."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels = None
depends_on = None


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


def downgrade() -> None:
    op.drop_table("templates")
    op.drop_constraint("uq_subtitle_replacements_user_source", "subtitle_replacements", type_="unique")
    op.drop_index("idx_subtitle_replacements_user", table_name="subtitle_replacements")
    op.drop_constraint("fk_subtitle_replacements_user", "subtitle_replacements", type_="foreignkey")
    op.drop_column("subtitle_replacements", "user_id")
    op.create_unique_constraint("subtitle_replacements_source_key", "subtitle_replacements", ["source"])
