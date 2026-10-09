"""用途：确认快照与审计ORM；边界：只保存服务端动作，不承担授权逻辑。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from odmflow.persistence import Base


class BusinessAction(Base):
    """一轮最多一个预览，revision和目标版本用于确认重验。"""

    __tablename__ = "business_actions"
    __table_args__ = (
        Index("ix_actions_owner_conversation", "owner_id", "conversation_id", "created_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(32), ForeignKey("user_account.id"))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"))
    turn_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_turns.id"), unique=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    parameters_json: Mapped[str] = mapped_column(String(8000))
    parameter_digest: Mapped[str] = mapped_column(String(64))
    target_order_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("orders.id"), nullable=True
    )
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    receipt_message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversation_messages.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    checkpoint_pruned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BusinessActionAudit(Base):
    """与动作状态同事务写入，不记录凭证、隐藏推理或原始请求头。"""

    __tablename__ = "business_action_audits"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    action_id: Mapped[str] = mapped_column(String(36), ForeignKey("business_actions.id"))
    status: Mapped[str] = mapped_column(String(32))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
