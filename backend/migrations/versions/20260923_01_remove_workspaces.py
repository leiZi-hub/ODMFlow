"""移除未采用的工作空间身份结构。

Revision ID: 20260923_01
Revises: 20260919_01

用途：
    将身份存储收敛为账号和服务端登录会话。

边界：
    不修改账号或会话数据；旧工作空间和成员数据在升级后无法恢复。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_01"
down_revision: str | None = "20260919_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """先删除成员关系，再删除工作空间表。"""

    op.drop_table("workspace_membership")
    op.drop_table("workspace")


def downgrade() -> None:
    """重建空表结构；原有工作空间和成员数据无法恢复。"""

    op.create_table(
        "workspace",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspace_membership",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user_account.id"]),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )
