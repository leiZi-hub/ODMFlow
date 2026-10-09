"""对话业务快照与错误契约。

用途：表达私人对话、分页、运行结果；不包含 ORM、HTTP 或模型框架。
边界：快照脱离数据库连接；字段校验和事务由各自适配层负责。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .operation_records import CitationSnapshot, OperationRecord

type Outcome = Literal["completed", "failed", "interrupted"]


class ConversationNotFound(Exception):
    """对话不存在或不属于当前账号。"""


class DuplicateTurn(Exception):
    """客户端请求 ID 已使用。"""


class TurnConflict(Exception):
    """同一对话已有未完成的运行。"""


@dataclass(frozen=True)
class ConversationView:
    """脱离数据库会话的对话快照。"""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class MessageView:
    """用户可见消息快照。"""

    id: int
    conversation_id: str
    role: str
    content: str
    kind: str
    created_at: datetime
    turn_id: str | None = None
    operations: tuple[OperationRecord, ...] = ()
    citations: tuple[CitationSnapshot, ...] = ()


@dataclass(frozen=True)
class ConversationPage:
    """最近对话的一页及更多标记。"""

    items: list[ConversationView]
    has_more: bool


@dataclass(frozen=True)
class MessagePage:
    """升序消息页及向前游标。"""

    items: list[MessageView]
    next_before_id: int | None


@dataclass(frozen=True)
class StartedTurn:
    """用户消息提交后的运行标识与历史。"""

    turn_id: str
    conversation_id: str
    user_message: MessageView
    history: list[tuple[str, str]]
    owner_id: str = ""


class ConversationStorageUnavailable(Exception):
    """存储未成功完成；不公开连接或驱动细节。"""


@dataclass(frozen=True)
class AcceptedTurn:
    """已原子提交的运行及新到旧历史候选；不含 ORM。"""

    turn_id: str
    conversation_id: str
    user_message: MessageView
    history_candidates: list[tuple[str, str]]
