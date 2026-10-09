"""用途：定义全用户画像版本和五个字段的SQL映射。边界：不定义权限、模型提取或私人向量库。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from odmflow.persistence import Base


class UserProfileState(Base):
    """用户级CAS版本，串联手动编辑与跨会话自动提取。"""

    __tablename__ = "user_profile_state"
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user_account.id"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)


class UserProfileField(Base):
    """一个有界字段；value为空代表删除抑制，不保存经历或聊天副本。"""

    __tablename__ = "user_profile_fields"
    owner_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("user_account.id"), primary_key=True
    )
    field_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    source_conversation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("conversations.id"), nullable=True
    )
    source_message_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("conversation_messages.id"), nullable=True
    )
    evidence: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
