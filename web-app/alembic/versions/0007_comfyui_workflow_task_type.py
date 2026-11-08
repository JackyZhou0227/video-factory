"""Rename digital-human tasks to the ComfyUI workflow task type."""

from typing import Sequence, Union

from alembic import op


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE generation_tasks "
        "SET task_type = 'comfyui_workflow' "
        "WHERE task_type = 'digital_human'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE generation_tasks "
        "SET task_type = 'digital_human' "
        "WHERE task_type = 'comfyui_workflow'"
    )
