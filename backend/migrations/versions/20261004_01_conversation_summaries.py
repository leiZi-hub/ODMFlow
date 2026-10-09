"""用途：新增派生摘要表；边界：不覆盖历史、不调用模型、不启动时自动执行。"""

import sqlalchemy as sa
from alembic import op

revision = "20261004_01"
down_revision = "20261002_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增摘要、CAS版本和来源覆盖指纹，既有聊天数据保持不变。"""
    op.create_table(
        "conversation_summaries",
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), primary_key=True
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("through_message_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """只删除可重建摘要表；原始对话与消息表不受影响。"""
    op.drop_table("conversation_summaries")
