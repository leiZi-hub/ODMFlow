"""用途：M7B确认快照、审计及售后表；边界：显式迁移，不创建演示记录。"""

import sqlalchemy as sa
from alembic import op

revision = "20261006_01"
down_revision = "20261005_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """保留旧订单，增加确认目标版本与唯一来源，以及独立受理表。"""
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("source_action_id", sa.String(36), nullable=True))
        batch.create_unique_constraint("uq_orders_source_action", ["source_action_id"])
    op.create_table(
        "business_actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column(
            "conversation_id", sa.String(36), sa.ForeignKey("conversations.id"), nullable=False
        ),
        sa.Column(
            "turn_id",
            sa.String(36),
            sa.ForeignKey("conversation_turns.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("parameters_json", sa.String(8000), nullable=False),
        sa.Column("parameter_digest", sa.String(64), nullable=False),
        sa.Column("target_order_id", sa.String(32), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("target_version", sa.Integer(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "receipt_message_id",
            sa.Integer(),
            sa.ForeignKey("conversation_messages.id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checkpoint_pruned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_actions_owner_conversation",
        "business_actions",
        ["owner_id", "conversation_id", "created_at"],
    )
    op.create_table(
        "business_action_audits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("action_id", sa.String(36), sa.ForeignKey("business_actions.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "after_sales_requests",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("application_no", sa.String(64), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("source_action_id", sa.String(36), nullable=False, unique=True),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("reproduction", sa.Text(), nullable=False),
        sa.Column("handling", sa.String(32), nullable=False),
        sa.Column("device_identifier", sa.String(120), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_after_sales_owner_created", "after_sales_requests", ["owner_id", "created_at", "id"]
    )
    op.create_table(
        "after_sales_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "request_id", sa.String(32), sa.ForeignKey("after_sales_requests.id"), nullable=False
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    """仅隔离测试回退；真实库会丢申请，不自动调用。"""
    op.drop_table("after_sales_events")
    op.drop_index("ix_after_sales_owner_created", table_name="after_sales_requests")
    op.drop_table("after_sales_requests")
    op.drop_table("business_action_audits")
    op.drop_index("ix_actions_owner_conversation", table_name="business_actions")
    op.drop_table("business_actions")
    with op.batch_alter_table("orders") as batch:
        batch.drop_constraint("uq_orders_source_action", type_="unique")
        batch.drop_column("source_action_id")
        batch.drop_column("version")
