"""用途：增加轮次操作快照和最终引用；边界：不改写历史消息或创建业务订单。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261002_01"
down_revision: str | None = "20260926_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """仅新增可空引用字段和按轮次关联的操作表，保留已有数据。"""
    op.add_column("conversation_turns", sa.Column("citations", sa.JSON(), nullable=True))
    op.create_table(
        "conversation_turn_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("turn_id", sa.String(36), sa.ForeignKey("conversation_turns.id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("elapsed_ms", sa.Integer()),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("turn_id", "sequence", name="uq_turn_operations_sequence"),
    )
    op.create_index("ix_turn_operations_turn", "conversation_turn_operations", ["turn_id"])


def downgrade() -> None:
    """删除本版本新增执行/引用快照，保留消息；回退并非诊断数据无损。"""
    op.drop_index("ix_turn_operations_turn", table_name="conversation_turn_operations")
    op.drop_table("conversation_turn_operations")
    with op.batch_alter_table("conversation_turns") as table:
        table.drop_column("citations")
