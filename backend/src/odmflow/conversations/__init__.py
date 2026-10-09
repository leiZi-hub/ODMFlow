"""对话公共用例与契约。

用途：导出跨包使用的对话服务、快照与业务错误。
边界：不暴露具体 ORM 或仓储。
"""

from .application import ConversationService
from .domain import (
    ConversationNotFound,
    ConversationStorageUnavailable,
    DuplicateTurn,
    MessageView,
    Outcome,
    StartedTurn,
    TurnConflict,
)

__all__ = [
    "ConversationService",
    "ConversationNotFound",
    "ConversationStorageUnavailable",
    "DuplicateTurn",
    "MessageView",
    "Outcome",
    "StartedTurn",
    "TurnConflict",
]
