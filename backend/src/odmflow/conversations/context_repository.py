"""用途：摘要SQL短事务、来源指纹和CAS；边界：不生成摘要、不持连接等待模型、不改变聊天原文。"""

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .context_contracts import (
    ContextHistory,
    ContextMessage,
    ContextRequest,
    ConversationSummarySnapshot,
)
from .domain import ConversationNotFound, ConversationStorageUnavailable, TurnConflict
from .models import Conversation, ConversationMessage, ConversationSummary, ConversationTurn


class SqlConversationContextRepository:
    """摘要派生存储；授权仍依赖当前对话与已接受轮次，不只检查summary行。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """注入每次操作的新Session工厂；构造不连接数据库。"""
        self._sessions = sessions

    @contextmanager
    def _session(self, write: bool = False) -> Iterator[Session]:
        """将驱动错误转换为公开领域错误，整个操作提交或回滚。"""
        try:
            with self._sessions() as database:
                yield database
                if write:
                    database.commit()
        except IntegrityError:
            raise TurnConflict from None
        except SQLAlchemyError:
            raise ConversationStorageUnavailable from None

    def load(
        self, request: ContextRequest, limit: int, keep: int, signature: str
    ) -> ContextHistory:
        """按可信身份读取未覆盖早期页和完整近期窗口。

        Args:
            request: 已接受轮次的身份、对话与当前用户消息上界。
            limit: 未覆盖页大小，1到128。
            keep: 最新完整消息数，1到64。
            signature: 当前摘要模型/模板签名。
        Returns:
            有效摘要、版本、原文页、近期窗口和来源摘要。
        Raises:
            ConversationNotFound: 他人或未知资源。
            TurnConflict: 当前轮已经终结或边界不匹配。
            ConversationStorageUnavailable: SQL失败。
        """
        if not 1 <= limit <= 128 or not 1 <= keep <= 64:
            raise ValueError("上下文页大小无效")
        with self._session() as database:
            _authorize(database, request)
            row = database.get(ConversationSummary, request.conversation_id)
            summary = None
            revision = row.version if row else 0
            if (
                row
                and row.signature == signature
                and row.through_message_id < request.before_message_id
                and row.source_digest
                == _digest(database, request.conversation_id, row.through_message_id + 1)
            ):
                summary = _snapshot(row)
            query = select(ConversationMessage).where(
                ConversationMessage.conversation_id == request.conversation_id,
                ConversationMessage.kind == "normal",
                ConversationMessage.id < request.before_message_id,
            )
            pending = database.scalars(
                query.where(ConversationMessage.id > (summary.through_message_id if summary else 0))
                .order_by(ConversationMessage.id)
                .limit(limit + 1)
            ).all()
            recent = database.scalars(
                query.order_by(ConversationMessage.id.desc()).limit(keep)
            ).all()
            return ContextHistory(
                summary,
                revision,
                tuple(_message(x) for x in pending[:limit]),
                tuple(_message(x) for x in reversed(recent)),
                len(pending) > limit,
                _digest(database, request.conversation_id, request.before_message_id),
            )

    def save(
        self,
        request: ContextRequest,
        history: ContextHistory,
        text: str,
        through_id: int,
        signature: str,
    ) -> ConversationSummarySnapshot:
        """锁定当前轮与版本、核对来源后更新摘要；模型调用在事务之外完成。

        Args:
            request: 原始可信运行边界。
            history: 生成摘要前读取的快照与来源指纹。
            text: 已由应用校验的非空有界摘要。
            through_id: 本页内实际覆盖的最后消息ID，不可跨越未读取消息。
            signature: 当前模板/模型签名。
        Returns:
            已提交摘要；调用方只能应用这个版本。
        Raises:
            TurnConflict: 来源、版本或运行改变。
            ConversationStorageUnavailable: SQL失败。
        """
        if not text.strip() or len(text.encode()) > 8192 or not signature:
            raise ValueError("摘要内容无效")
        if through_id not in {x.id for x in history.pending}:
            raise ValueError("摘要覆盖边界不在已读取页内")
        with self._session(write=True) as database:
            _authorize(database, request, lock=True)
            row = database.get(ConversationSummary, request.conversation_id)
            if (row.version if row else 0) != history.revision or history.archive_digest != _digest(
                database, request.conversation_id, request.before_message_id
            ):
                raise TurnConflict
            source_digest = _digest(database, request.conversation_id, through_id + 1)
            if row is None:
                row = ConversationSummary(conversation_id=request.conversation_id)
                database.add(row)
            row.text = text
            row.through_message_id = through_id
            row.version = history.revision + 1
            row.signature = signature
            row.source_digest = source_digest
            row.updated_at = datetime.now(UTC)
            result = _snapshot(row)
        return result


def _authorize(database: Session, request: ContextRequest, lock: bool = False) -> None:
    """归属隐藏404；保存时与终结事务共用对话行锁和running门禁。"""
    query = select(Conversation).where(Conversation.id == request.conversation_id)
    if lock:
        query = query.with_for_update()
    conversation = database.scalar(query)
    if conversation is None or conversation.user_id != request.owner_id:
        raise ConversationNotFound
    turn = database.get(ConversationTurn, request.turn_id)
    if (
        turn is None
        or turn.conversation_id != request.conversation_id
        or turn.status != "running"
        or turn.user_message_id != request.before_message_id
        or conversation.current_turn_id != request.turn_id
    ):
        raise TurnConflict


def _digest(database: Session, conversation_id: str, before_id: int) -> str:
    """有界迭代所有已覆盖normal来源，防止改原文/删来源后继续复用旧摘要。"""
    digest = hashlib.sha256()
    query = (
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.kind == "normal",
            ConversationMessage.id < before_id,
        )
        .order_by(ConversationMessage.id)
        .execution_options(yield_per=64)
    )
    for row in database.scalars(query):
        digest.update(json.dumps([row.id, row.role, row.content], ensure_ascii=False).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def _message(row: ConversationMessage) -> ContextMessage:
    """将ORM行转为无连接的完整消息。"""
    return ContextMessage(row.id, row.role, row.content)


def _snapshot(row: ConversationSummary) -> ConversationSummarySnapshot:
    """只返回已保存字段，不返回ORM状态。"""
    return ConversationSummarySnapshot(row.text, row.through_message_id, row.version, row.signature)
