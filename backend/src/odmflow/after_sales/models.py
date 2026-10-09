"""用途：模拟售后记录与事件映射；边界：无身份选择或真实审批流程。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from odmflow.persistence import Base


class AfterSalesRequest(Base):
    """确认后唯一创建的受理意向，归属独立于会话。"""

    __tablename__ = "after_sales_requests"
    __table_args__ = (Index("ix_after_sales_owner_created", "owner_id", "created_at", "id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    application_no: Mapped[str] = mapped_column(String(64), unique=True)
    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("user_account.id"))
    order_id: Mapped[str] = mapped_column(String(32), ForeignKey("orders.id"))
    source_action_id: Mapped[str] = mapped_column(String(36), unique=True)
    symptom: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[str] = mapped_column(Text)
    reproduction: Mapped[str] = mapped_column(Text)
    handling: Mapped[str] = mapped_column(String(32))
    device_identifier: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AfterSalesEvent(Base):
    """与受理行同事务创建的事实事件。"""

    __tablename__ = "after_sales_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(32), ForeignKey("after_sales_requests.id"))
    status: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
