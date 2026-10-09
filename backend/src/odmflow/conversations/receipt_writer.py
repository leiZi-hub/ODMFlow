"""用途：业务回执的对话SQL投影；边界：不决定业务是否成功，不调用LLM或独立commit。"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Conversation, ConversationMessage


def append_receipt(
    session: Session, owner_id: str, conversation_id: str, text: str, now: datetime
) -> int:
    """调用方的短事务写入本人助手回执，返回消息ID；失败不改变已提交业务。"""
    row = session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == owner_id
        )
    )
    if row is None:
        raise ValueError("receipt_conversation_not_found")
    message = ConversationMessage(
        conversation_id=conversation_id,
        role="assistant",
        content=text,
        kind="normal",
        created_at=now,
    )
    session.add(message)
    row.updated_at = now
    session.flush()
    return message.id
