"""创建私人对话、可见消息和运行记录三表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_01"
down_revision: str | None = "20260923_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立归属、消息分页和幂等运行所需结构。"""

    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("current_turn_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversations_owner_updated", "conversations", ["user_id", "updated_at"])
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversation_messages_page", "conversation_messages", ["conversation_id", "id"]
    )
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column(
            "user_message_id",
            sa.Integer(),
            sa.ForeignKey("conversation_messages.id"),
            nullable=False,
        ),
        sa.Column("assistant_message_id", sa.Integer(), sa.ForeignKey("conversation_messages.id")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_conversation_turns_conversation", "conversation_turns", ["conversation_id"])


def downgrade() -> None:
    """按依赖顺序移除 M3 三表；回滚会删除对话数据。"""

    op.drop_index("ix_conversation_turns_conversation", table_name="conversation_turns")
    op.drop_table("conversation_turns")
    op.drop_index("ix_conversation_messages_page", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_conversations_owner_updated", table_name="conversations")
    op.drop_table("conversations")
