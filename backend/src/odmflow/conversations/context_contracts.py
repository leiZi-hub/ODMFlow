"""用途：定义会话摘要和有界历史快照；边界：不依赖模型、SQL或HTTP，不代表跨会话画像。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextRequest:
    """服务端注入的归属与运行边界，不接受模型自报身份。"""

    owner_id: str
    conversation_id: str
    turn_id: str
    before_message_id: int


@dataclass(frozen=True)
class ContextMessage:
    """用于覆盖游标的完整原始消息，不包含工具协议。"""

    id: int
    role: str
    content: str


@dataclass(frozen=True)
class ConversationSummarySnapshot:
    """有效派生摘要；原文仍在消息表，摘要不是权威业务事实。"""

    text: str
    through_message_id: int
    version: int
    signature: str


@dataclass(frozen=True)
class ContextHistory:
    """脱离Session的有界页；revision也保留失效摘要的CAS版本。"""

    summary: ConversationSummarySnapshot | None
    revision: int
    pending: tuple[ContextMessage, ...]
    recent: tuple[ContextMessage, ...]
    has_more: bool
    archive_digest: str
