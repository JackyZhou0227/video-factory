"""Drop creator name snapshot columns from generation_tasks."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("generation_tasks", "creator_display_name")
    op.drop_column("generation_tasks", "creator_username")


def downgrade() -> None:
    op.add_column(
        "generation_tasks",
        sa.Column("creator_username", sa.Text(), nullable=True),
    )
    op.add_column(
        "generation_tasks",
        sa.Column("creator_display_name", sa.Text(), nullable=True),
    )
    op.execute(
        "UPDATE generation_tasks AS t "
        "SET creator_username = u.username, "
        "    creator_display_name = COALESCE(u.display_name, u.username) "
        "FROM users AS u "
        "WHERE u.id = t.user_id"
    )
    op.alter_column("generation_tasks", "creator_username", nullable=False)
    op.alter_column("generation_tasks", "creator_display_name", nullable=False)
