"""Add organizations, org-scoped roles and registration approval status."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels = None
depends_on = None


# Full definition of the target users table. SQLite cannot alter or drop an
# unnamed CHECK constraint in place, so batch mode recreates the table from
# this definition (copy data, drop old, rename). On PostgreSQL the same batch
# operations degrade to plain ALTER TABLE statements.
USERS_TARGET = sa.Table(
    "users",
    sa.MetaData(),
    sa.Column("id", sa.Text(), primary_key=True),
    sa.Column("username", sa.Text(), nullable=False),
    sa.Column("display_name", sa.Text(), nullable=False),
    sa.Column("role", sa.Text(), server_default=sa.text("'user'"), nullable=False),
    sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
    sa.Column("org_id", sa.Text(), nullable=True),
    sa.Column("password_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column("password_salt", sa.Text(), server_default=sa.text("''"), nullable=False),
    sa.Column("password_iterations", sa.Integer(), server_default=sa.text("0"), nullable=False),
    sa.Column("is_default", sa.Integer(), server_default=sa.text("0"), nullable=False),
    sa.Column("created_at", sa.Text(), nullable=False),
    sa.Column("updated_at", sa.Text(), nullable=False),
    sa.CheckConstraint("role IN ('user', 'org_admin', 'admin')"),
    sa.CheckConstraint("status IN ('active', 'pending')"),
    sa.CheckConstraint("is_default IN (0, 1)"),
    sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="SET NULL"),
    sa.UniqueConstraint("username"),
)


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("name", name="uq_organizations_name"),
        comment="组织（行政归属单位，用于人员归属与管理口径）",
    )

    with op.batch_alter_table("users", copy_from=USERS_TARGET) as batch_op:
        batch_op.add_column(sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False))
        batch_op.add_column(sa.Column("org_id", sa.Text(), nullable=True))

    # On SQLite the batch recreate above already installed the new CHECK
    # constraints and FK. On PostgreSQL batch mode degrades to plain ALTER
    # TABLE, so the role CHECK must be replaced and the new ones added here.
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("users_role_check", "users", type_="check")
        op.create_check_constraint("users_role_check", "users", "role IN ('user', 'org_admin', 'admin')")
        op.create_check_constraint("users_status_check", "users", "status IN ('active', 'pending')")
        op.create_foreign_key(
            "fk_users_org_id_organizations",
            "users",
            "organizations",
            ["org_id"],
            ["id"],
            ondelete="SET NULL",
        )

    for table, column, comment in (
        ("organizations", "id", "组织唯一标识"),
        ("organizations", "name", "组织名称"),
        ("organizations", "created_at", "创建时间"),
        ("organizations", "updated_at", "更新时间"),
        ("users", "role", "用户角色"),
        ("users", "status", "账号状态（active 正常 / pending 待审批）"),
        ("users", "org_id", "所属组织标识"),
    ):
        op.execute(f"COMMENT ON COLUMN {table}.{column} IS '{comment}'")


def downgrade() -> None:
    USERS_OLD = sa.Table(
        "users",
        sa.MetaData(),
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'user'"), nullable=False),
        sa.Column("password_hash", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("password_salt", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("password_iterations", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_default", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("role IN ('user', 'admin')"),
        sa.CheckConstraint("is_default IN (0, 1)"),
        sa.UniqueConstraint("username"),
    )

    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("users_role_check", "users", type_="check")
        op.create_check_constraint("users_role_check", "users", "role IN ('user', 'admin')")
        op.drop_constraint("users_status_check", "users", type_="check")
        op.drop_constraint("fk_users_org_id_organizations", "users", type_="foreignkey")
        op.drop_column("users", "org_id")
        op.drop_column("users", "status")
    else:
        with op.batch_alter_table("users", copy_from=USERS_OLD) as batch_op:
            pass

    op.drop_table("organizations")
