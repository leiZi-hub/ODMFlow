"""用途：新增结构化用户画像与CAS版本；边界：不修改原会话/摘要，不创建私人记忆向量库。"""

import sqlalchemy as sa
from alembic import op

revision = "20261005_01"
down_revision = "20261004_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建两张用户级画像表；现有消息及摘要保持原样。"""
    op.create_table(
        "user_profile_state",
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("user_account.id"), primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
    )
    op.create_table(
        "user_profile_fields",
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("user_account.id"), primary_key=True),
        sa.Column("field_key", sa.String(32), primary_key=True),
        sa.Column("value", sa.String(80), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column(
            "source_conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id"),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            sa.Integer(),
            sa.ForeignKey("conversation_messages.id"),
            nullable=True,
        ),
        sa.Column("evidence", sa.String(256), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """仅删除本次两表；回滚会丢画像，原始会话与摘要不删除。"""
    op.drop_table("user_profile_fields")
    op.drop_table("user_profile_state")
