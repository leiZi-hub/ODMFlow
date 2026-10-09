"""用途：新增独立模拟订单与进度表。边界：不生成样本、不修改既有身份/会话/画像。"""

import sqlalchemy as sa
from alembic import op

revision = "20261005_02"
down_revision = "20261005_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建本人归属和稳定分页索引；需显式执行迁移。"""
    op.create_table(
        "orders",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("order_no", sa.String(64), nullable=False, unique=True),
        sa.Column("owner_id", sa.String(32), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("product_model", sa.String(80), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("target_market", sa.String(80), nullable=False),
        sa.Column("configuration_summary", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("demo_batch", sa.String(64), nullable=True),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity"),
        sa.CheckConstraint(
            "status in ('pending_review','in_production','delivered','cancelled')",
            name="ck_orders_status",
        ),
    )
    op.create_index("ix_orders_owner_created_id", "orders", ["owner_id", "created_at", "id"])
    op.create_table(
        "order_progress_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("order_id", sa.String(32), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status in ('pending_review','in_production','delivered','cancelled')",
            name="ck_order_progress_status",
        ),
    )
    op.create_index(
        "ix_order_progress_order_time_id",
        "order_progress_events",
        ["order_id", "occurred_at", "id"],
    )


def downgrade() -> None:
    """仅隔离环境验证回滚；真实库执行会丢订单，不自动调用。"""
    op.drop_index("ix_order_progress_order_time_id", table_name="order_progress_events")
    op.drop_table("order_progress_events")
    op.drop_index("ix_orders_owner_created_id", table_name="orders")
    op.drop_table("orders")
