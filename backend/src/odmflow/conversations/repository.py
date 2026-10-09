"""对话 SQL 仓储。

用途：实现粗粒度仓储端口、归属条件与原子短事务。
边界：不处理 HTTP、模型、保底文本或历史字符预算；驱动异常转业务错误。
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .domain import (
    AcceptedTurn,
    ConversationNotFound,
    ConversationPage,
    ConversationStorageUnavailable,
    ConversationView,
    DuplicateTurn,
    MessagePage,
    MessageView,
    Outcome,
    TurnConflict,
)
from .models import Conversation, ConversationMessage, ConversationTurn, ConversationTurnOperation
from .operation_records import CitationSnapshot, JsonValue, OperationRecord, OperationState


class SqlConversationRepository:
    """以短事务实现对话仓储端口；不决定模型或历史预算策略。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """保存工厂；不持有数据库会话。

        Args:
            sessions: 每次操作创建独立会话的工厂。
        Returns:
            无；不连接数据库。
        """
        self._sessions = sessions

    def accept_turn(
        self,
        owner_id: str,
        conversation_id: str | None,
        new_conversation_id: str,
        client_turn_id: str,
        message: str,
        title: str,
        now: datetime,
        history_limit: int,
    ) -> AcceptedTurn:
        """按仓储端口约定原子接受用户消息；异常时整笔回滚。

        Args:
            owner_id: 服务端验证的账号。
            conversation_id: 既有对话标识，None 时新建。
            new_conversation_id: 应用层生成的新对话标识。
            client_turn_id: 唯一请求标识。
            message: 已校验用户文本。
            title: 新对话标题。
            now: 写入时间。
            history_limit: 正常历史候选上限。
        Returns:
            已提交的运行、消息与新到旧历史候选。
        Raises:
            ConversationNotFound: 未知或他人的对话。
            DuplicateTurn: 请求标识已使用。
            TurnConflict: 对话占用或完整性冲突。
            ConversationStorageUnavailable: 驱动失败，整笔回滚。
        """

        with self._session(write=True, conflict_on_integrity=True) as database:
            if database.get(ConversationTurn, client_turn_id) is not None:
                raise DuplicateTurn
            if conversation_id is None:
                conversation_id = new_conversation_id
                database.add(
                    Conversation(
                        id=conversation_id,
                        user_id=owner_id,
                        title=title,
                        current_turn_id=client_turn_id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                database.flush()
            else:
                conversation = database.get(Conversation, conversation_id)
                if conversation is None or conversation.user_id != owner_id:
                    raise ConversationNotFound
                if conversation.current_turn_id is not None:
                    raise TurnConflict
                claimed = database.execute(
                    update(Conversation)
                    .where(
                        Conversation.id == conversation_id, Conversation.current_turn_id.is_(None)
                    )
                    .values(current_turn_id=client_turn_id, updated_at=now)
                )
                if cast(CursorResult[Any], claimed).rowcount != 1:
                    raise TurnConflict
            history = self._history_candidates(database, conversation_id, history_limit)
            saved = ConversationMessage(
                conversation_id=conversation_id,
                role="user",
                content=message,
                kind="normal",
                created_at=now,
            )
            database.add(saved)
            database.flush()
            database.add(
                ConversationTurn(
                    id=client_turn_id,
                    conversation_id=conversation_id,
                    user_message_id=saved.id,
                    assistant_message_id=None,
                    status="running",
                    created_at=now,
                    updated_at=now,
                )
            )
            snapshot = _message_view(saved)
        return AcceptedTurn(client_turn_id, conversation_id, snapshot, history)

    def finish_turn(
        self,
        turn_id: str,
        content: str,
        outcome: Outcome,
        now: datetime,
        citations: tuple[CitationSnapshot, ...] = (),
    ) -> MessageView:
        """在同一短事务保存回复并释放对话占用。

        Args:
            turn_id: 待终结的运行标识。
            content: 最终回复或保底文本。
            outcome: 运行终态。
            now: 终态写入时间。
        Returns:
            提交后的助手消息快照。
        Raises:
            TurnConflict: 运行不存在或已终结。
            ConversationStorageUnavailable: 驱动失败，回复、终态和占用均回滚。
        """

        with self._session(write=True) as database:
            turn = database.scalar(
                select(ConversationTurn).where(ConversationTurn.id == turn_id).with_for_update()
            )
            if turn is None or turn.status != "running":
                raise TurnConflict
            saved = ConversationMessage(
                conversation_id=turn.conversation_id,
                role="assistant",
                content=content,
                kind="normal" if outcome == "completed" else "fallback",
                created_at=now,
            )
            database.add(saved)
            database.flush()
            turn.assistant_message_id = saved.id
            turn.status = outcome
            turn.updated_at = now
            turn.citations = [cast(dict[str, JsonValue], asdict(source)) for source in citations]
            running_operations = database.scalars(
                select(ConversationTurnOperation).where(
                    ConversationTurnOperation.turn_id == turn_id,
                    ConversationTurnOperation.status == "running",
                )
            ).all()
            for operation in running_operations:
                operation.status = "interrupted"
                operation.finished_at = now
            database.flush()
            database.execute(
                update(Conversation)
                .where(
                    Conversation.id == turn.conversation_id, Conversation.current_turn_id == turn_id
                )
                .values(current_turn_id=None, updated_at=now)
            )
            operations = database.scalars(
                select(ConversationTurnOperation)
                .where(ConversationTurnOperation.turn_id == turn_id)
                .order_by(ConversationTurnOperation.sequence)
            ).all()
            snapshot = _message_view(saved, turn, tuple(_operation_view(row) for row in operations))
        return snapshot

    def start_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """验证正在运行的私人轮次后保存开始快照。

        Args:
            owner_id: 已验证账号。
            conversation_id: 当前对话。
            turn_id: 对话所属轮次。
            record: 版本化快照，不含身份自报参数。
        Returns:
            已提交开始记录。
        Raises:
            ConversationNotFound: 归属不符。
            TurnConflict: 重复/终结轮次或非法生命周期。
        """
        payload = record.payload()
        with self._session(write=True, conflict_on_integrity=True) as database:
            turn = self._owned_turn(database, owner_id, conversation_id, turn_id, lock=True)
            if (
                turn.status != "running"
                or record.turn_id != turn_id
                or record.status != "running"
                or record.sequence < 1
            ):
                raise TurnConflict
            row = ConversationTurnOperation(
                id=record.id,
                turn_id=turn_id,
                sequence=record.sequence,
                status="running",
                started_at=record.started_at,
                payload=payload,
            )
            database.add(row)
            database.flush()
            snapshot = _operation_view(row)
        return snapshot

    def finish_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """锁定仍运行的轮次和操作，完整替换JSON以确保更新持久化。

        Args:
            owner_id: 已验证账号。
            conversation_id: 当前对话。
            turn_id: 当前轮次。
            record: 同一操作的终态快照。
        Returns:
            已提交操作快照。
        Raises:
            ConversationNotFound: 不可见资源。
            TurnConflict: 操作不匹配、已结束或轮次已结束。
        """
        payload = record.payload()
        with self._session(write=True) as database:
            turn = self._owned_turn(database, owner_id, conversation_id, turn_id, lock=True)
            row = database.get(ConversationTurnOperation, record.id)
            if (
                turn.status != "running"
                or record.turn_id != turn_id
                or row is None
                or row.turn_id != turn_id
                or row.sequence != record.sequence
                or row.status != "running"
                or record.status == "running"
            ):
                raise TurnConflict
            row.status = record.status
            row.finished_at = record.finished_at
            row.elapsed_ms = record.elapsed_ms
            row.payload = payload
            database.flush()
            snapshot = _operation_view(row)
        return snapshot

    def list_operations(
        self, owner_id: str, conversation_id: str, turn_id: str
    ) -> tuple[OperationRecord, ...]:
        """验证对话与轮次配对后返回序号顺序快照。

        Args:
            owner_id: 登录主体。
            conversation_id: 对话标识。
            turn_id: 必须属于该对话的轮次。
        Returns:
            内部快照，API统一过滤详情。
        Raises:
            ConversationNotFound: 不可见资源。
        """
        with self._session() as database:
            self._owned_turn(database, owner_id, conversation_id, turn_id)
            return tuple(
                _operation_view(row)
                for row in database.scalars(
                    select(ConversationTurnOperation)
                    .where(ConversationTurnOperation.turn_id == turn_id)
                    .order_by(ConversationTurnOperation.sequence)
                )
            )

    @staticmethod
    def _owned_turn(
        database: Session, owner_id: str, conversation_id: str, turn_id: str, lock: bool = False
    ) -> ConversationTurn:
        """用一条归属条件查询禁止跨账号或跨对话拼接轮次。"""
        query = (
            select(ConversationTurn)
            .join(Conversation)
            .where(
                Conversation.user_id == owner_id,
                Conversation.id == conversation_id,
                ConversationTurn.id == turn_id,
            )
        )
        row = database.scalar(query.with_for_update() if lock else query)
        if row is None:
            raise ConversationNotFound
        return row

    def list_conversations(self, owner_id: str, limit: int, offset: int) -> ConversationPage:
        """只查询当前账号对话；过期收口由应用层负责。

        Args:
            owner_id: 已验证账号。
            limit: 本页数量上限。
            offset: 跳过的对话数量。
        Returns:
            最近更新优先的对话页和是否还有下一页。
        Raises:
            ConversationStorageUnavailable: 数据库读取失败。
        """

        with self._session() as database:
            rows = database.scalars(
                select(Conversation)
                .where(Conversation.user_id == owner_id)
                .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                .offset(offset)
                .limit(limit + 1)
            ).all()
            return ConversationPage(
                [_conversation_view(row) for row in rows[:limit]], len(rows) > limit
            )

    def list_messages(
        self, owner_id: str, conversation_id: str, limit: int, before_id: int | None
    ) -> MessagePage:
        """验证归属，返回最新或游标之前的升序消息页。

        Args:
            owner_id: 已验证账号。
            conversation_id: 待查询对话。
            limit: 本页数量上限。
            before_id: 查询该消息之前的内容，None 查询最新一页。
        Returns:
            升序消息快照与更早消息的游标。
        Raises:
            ConversationNotFound: 未知或他人的对话。
            ConversationStorageUnavailable: 数据库读取失败。
        """

        with self._session() as database:
            conversation = database.get(Conversation, conversation_id)
            if conversation is None or conversation.user_id != owner_id:
                raise ConversationNotFound
            query = select(ConversationMessage).where(
                ConversationMessage.conversation_id == conversation_id
            )
            if before_id is not None:
                query = query.where(ConversationMessage.id < before_id)
            rows = database.scalars(
                query.order_by(ConversationMessage.id.desc()).limit(limit + 1)
            ).all()
            page = rows[:limit]
            cursor = page[-1].id if len(rows) > limit and page else None
            ids = [row.id for row in page]
            turns = database.scalars(
                select(ConversationTurn).where(
                    ConversationTurn.conversation_id == conversation_id,
                    or_(
                        ConversationTurn.user_message_id.in_(ids),
                        ConversationTurn.assistant_message_id.in_(ids),
                    ),
                )
            ).all()
            by_message: dict[int, ConversationTurn] = {}
            for turn in turns:
                by_message[turn.user_message_id] = turn
                if turn.assistant_message_id is not None:
                    by_message[turn.assistant_message_id] = turn
            by_turn: dict[str, list[OperationRecord]] = {}
            operations = database.scalars(
                select(ConversationTurnOperation)
                .where(ConversationTurnOperation.turn_id.in_([turn.id for turn in turns]))
                .order_by(ConversationTurnOperation.sequence)
            ).all()
            for operation in operations:
                by_turn.setdefault(operation.turn_id, []).append(_operation_view(operation))
            return MessagePage(
                [
                    _message_view(
                        row,
                        by_message.get(row.id),
                        tuple(by_turn.get(by_message[row.id].id, []))
                        if row.id in by_message
                        else (),
                    )
                    for row in reversed(page)
                ],
                cursor,
            )

    def find_stale_turn_ids(self, owner_id: str, threshold: datetime) -> list[str]:
        """按账号与截止时间查询残留运行；不执行恢复策略。

        Args:
            owner_id: 已验证账号。
            threshold: 早于该时间且仍运行的记录才返回。
        Returns:
            待恢复的运行标识列表。
        Raises:
            ConversationStorageUnavailable: 数据库读取失败。
        """
        with self._session() as database:
            return list(
                database.scalars(
                    select(ConversationTurn.id)
                    .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
                    .where(
                        Conversation.user_id == owner_id,
                        ConversationTurn.status == "running",
                        ConversationTurn.created_at < threshold,
                    )
                ).all()
            )

    @contextmanager
    def _session(
        self, write: bool = False, conflict_on_integrity: bool = False
    ) -> Iterator[Session]:
        """限定存储会话并在事务回滚后翻译驱动错误。"""
        try:
            with self._sessions() as database:
                with database.begin() if write else nullcontext():
                    yield database
        except IntegrityError as error:
            if conflict_on_integrity:
                raise TurnConflict from error
            raise ConversationStorageUnavailable from error
        except SQLAlchemyError as error:
            raise ConversationStorageUnavailable from error

    @staticmethod
    def _history_candidates(
        database: Session, conversation_id: str, limit: int
    ) -> list[tuple[str, str]]:
        """按新到旧返回正常消息候选；字符预算由应用层处理。"""

        rows = database.scalars(
            select(ConversationMessage)
            .where(
                ConversationMessage.conversation_id == conversation_id,
                ConversationMessage.kind == "normal",
            )
            .order_by(ConversationMessage.id.desc())
            .limit(limit)
        ).all()
        return [(row.role, row.content) for row in rows]


def _conversation_view(row: Conversation) -> ConversationView:
    return ConversationView(row.id, row.title, row.created_at, row.updated_at)


def _message_view(
    row: ConversationMessage,
    turn: ConversationTurn | None = None,
    operations: tuple[OperationRecord, ...] = (),
) -> MessageView:
    citations = (
        tuple(CitationSnapshot(**cast(dict[str, str], source)) for source in (turn.citations or []))
        if turn and row.role == "assistant"
        else ()
    )
    return MessageView(
        row.id,
        row.conversation_id,
        row.role,
        row.content,
        row.kind,
        row.created_at,
        turn.id if turn else None,
        operations,
        citations,
    )


def _operation_view(row: ConversationTurnOperation) -> OperationRecord:
    """脱离ORM并规范SQLite读取的无时区UTC值，保持跨库快照一致。"""
    return OperationRecord(
        id=row.id,
        turn_id=row.turn_id,
        sequence=row.sequence,
        status=cast(OperationState, row.status),
        started_at=row.started_at.replace(tzinfo=UTC)
        if row.started_at.tzinfo is None
        else row.started_at,
        finished_at=(
            row.finished_at.replace(tzinfo=UTC)
            if row.finished_at.tzinfo is None
            else row.finished_at
        )
        if row.finished_at
        else None,
        elapsed_ms=row.elapsed_ms,
        payload_json=json.dumps(row.payload, ensure_ascii=False, separators=(",", ":")),
    )
