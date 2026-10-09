"""用途：订单及进度ORM映射。边界：不定义授权或启动时建表。"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from odmflow.persistence import Base


class Order(Base):
    """独立于对话的模拟订单，归属用户。"""

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_owner_created_id", "owner_id", "created_at", "id"),
        CheckConstraint("quantity > 0", name="ck_orders_quantity"),
        CheckConstraint(
            "status in ('pending_review','in_production','delivered','cancelled')",
            name="ck_orders_status",
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("user_account.id"), nullable=False)
    product_model: Mapped[str] = mapped_column(String(80), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    target_market: Mapped[str] = mapped_column(String(80), nullable=False)
    configuration_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    demo_batch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    source_action_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)


class OrderProgressEvent(Base):
    """订单进度事实行；无独立用户可选归属字段。"""

    __tablename__ = "order_progress_events"
    __table_args__ = (
        Index("ix_order_progress_order_time_id", "order_id", "occurred_at", "id"),
        CheckConstraint(
            "status in ('pending_review','in_production','delivered','cancelled')",
            name="ck_order_progress_status",
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
