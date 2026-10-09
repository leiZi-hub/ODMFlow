"""私人对话数据库映射；不执行授权或业务流程。"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from odmflow.persistence import Base

from .operation_records import JsonValue


class Conversation(Base):
    """单个账号的可见对话和当前运行占用。"""

    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("user_account.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    current_turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_conversations_owner_updated", "user_id", "updated_at"),)


class ConversationMessage(Base):
    """用户可见文本；不保存原始工具结果或提示词。"""

    __tablename__ = "conversation_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_conversation_messages_page", "conversation_id", "id"),)


class ConversationTurn(Base):
    """请求幂等记录及中断恢复状态。"""

    __tablename__ = "conversation_turns"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=False
    )
    user_message_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("conversation_messages.id"), nullable=False
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversation_messages.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    citations: Mapped[list[dict[str, JsonValue]] | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (Index("ix_conversation_turns_conversation", "conversation_id"),)


class ConversationSummary(Base):
    """可重建会话摘要与来源覆盖标记；归属通过对话外键核验，不替换原文。"""

    __tablename__ = "conversation_summaries"
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id"), primary_key=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    through_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConversationTurnOperation(Base):
    """轮内真实操作的短事务快照；不保存凭证或模型隐藏推理。"""

    __tablename__ = "conversation_turn_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    turn_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversation_turns.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSON, nullable=False)
    __table_args__ = (
        UniqueConstraint("turn_id", "sequence", name="uq_turn_operations_sequence"),
        Index("ix_turn_operations_turn", "turn_id"),
    )
