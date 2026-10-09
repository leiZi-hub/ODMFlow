"""用途：画像SQL短事务、全用户CAS和本人原文核验。边界：不等待LLM、不替代会话摘要、不作语义判断。"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from odmflow.conversations.context_contracts import ContextRequest
from odmflow.conversations.models import Conversation, ConversationMessage, ConversationTurn
from odmflow.identity.models import UserAccount

from .domain import (
    ProfileCandidate,
    ProfileConflict,
    ProfileInputSnapshot,
    ProfileItem,
    ProfileSnapshot,
    ProfileSource,
    ProfileSourceInvalid,
    ProfileUnavailable,
)
from .models import UserProfileField, UserProfileState


class SqlProfileRepository:
    """每次操作新Session，写入按账号串行核验，不跨模型等待持锁。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """注入会话工厂，构造不连接数据库。"""
        self._sessions = sessions

    @contextmanager
    def _session(self, write: bool = False) -> Iterator[Session]:
        """原子提交/回滚并转换驱动错误，避免错误泄漏。"""
        try:
            with self._sessions() as database:
                yield database
                if write:
                    database.commit()
        except IntegrityError:
            raise ProfileConflict from None
        except SQLAlchemyError:
            raise ProfileUnavailable from None

    def read(self, owner: str) -> ProfileSnapshot:
        """返回本人字段，未建立画像时返回revision0空列表。"""
        with self._session() as database:
            return _snapshot(database, owner)

    def change(self, owner: str, revision: int, key: str, value: str | None) -> ProfileSnapshot:
        """按全用户版本编辑；删除保留抑制行，手动设置可恢复。"""
        with self._session(True) as database:
            state = _lock_state(database, owner, revision)
            row = database.get(UserProfileField, (owner, key))
            desired_origin = "manual" if value is not None else "deleted"
            if row is not None and row.origin == desired_origin and row.value == value:
                return _snapshot(database, owner)
            if row is None:
                row = UserProfileField(owner_id=owner, field_key=key)
                database.add(row)
            row.value = value
            row.origin = desired_origin
            row.source_message_id = None
            row.source_conversation_id = None
            row.evidence = None
            row.updated_at = datetime.now(UTC)
            state.revision += 1
            database.flush()
            return _snapshot(database, owner)

    def load_sources(self, request: ContextRequest, limit: int) -> ProfileInputSnapshot:
        """只读取当前会话正常用户消息，不扫描其他会话或助手推测。"""
        with self._session() as database:
            _authorize(database, request)
            messages = database.scalars(
                select(ConversationMessage)
                .where(
                    ConversationMessage.conversation_id == request.conversation_id,
                    ConversationMessage.role == "user",
                    ConversationMessage.kind == "normal",
                    ConversationMessage.id <= request.before_message_id,
                )
                .order_by(ConversationMessage.id.desc())
                .limit(limit)
            ).all()
            return ProfileInputSnapshot(
                _snapshot(database, request.owner_id),
                tuple(ProfileSource(x.id, x.content) for x in reversed(messages)),
            )

    def apply_candidates(
        self,
        request: ContextRequest,
        snapshot: ProfileInputSnapshot,
        candidates: tuple[ProfileCandidate, ...],
    ) -> ProfileSnapshot:
        """复核来源原文和版本；手动/删除字段优先，旧消息不改新值。

        Args:
            request: 服务端当前轮边界。
            snapshot: 提取前释放SQL连接的完整快照。
            candidates: 已校验的最多五个不同字段候选。
        Returns:
            已提交结果；无资格变更不增加版本。
        Raises:
            ProfileConflict: 快照迟到。
            ProfileSourceInvalid: 原文、归属、重复字段或运行边界无效。
            ProfileUnavailable: 数据库失败。
        """
        if len(candidates) > 5 or len({x.field_key for x in candidates}) != len(candidates):
            raise ProfileSourceInvalid
        with self._session(True) as database:
            # 账号/CAS先串行，再以与finish_turn相同的轮次→会话顺序锁当前状态。
            # 锁仅覆盖候选短事务；提取模型等待早已结束。
            state = _lock_state(database, request.owner_id, snapshot.profile.revision)
            _authorize(database, request, lock=True)
            originals = {x.message_id: x.content for x in snapshot.sources}
            for item in candidates:
                source = database.get(ConversationMessage, item.source_message_id)
                if (
                    source is None
                    or source.role != "user"
                    or source.kind != "normal"
                    or source.conversation_id != request.conversation_id
                    or source.id > request.before_message_id
                    or originals.get(source.id) != source.content
                    or item.evidence not in source.content
                ):
                    raise ProfileSourceInvalid
            changed = False
            for item in candidates:
                row = database.get(UserProfileField, (request.owner_id, item.field_key.value))
                if row is not None and (
                    row.origin in {"manual", "deleted"}
                    or (row.source_message_id or 0) >= item.source_message_id
                ):
                    continue
                if row is None:
                    row = UserProfileField(
                        owner_id=request.owner_id, field_key=item.field_key.value
                    )
                    database.add(row)
                row.value, row.origin = item.value, "conversation"
                row.source_conversation_id = request.conversation_id
                row.source_message_id, row.evidence = item.source_message_id, item.evidence
                row.updated_at = datetime.now(UTC)
                changed = True
            if changed:
                state.revision += 1
            database.flush()
            return _snapshot(database, request.owner_id)


def _authorize(database: Session, request: ContextRequest, *, lock: bool = False) -> None:
    """核验当前运行边界；写入使用当前读行锁，与终结事务串行到提交。"""
    turn_query = select(ConversationTurn).where(ConversationTurn.id == request.turn_id)
    conversation_query = select(Conversation).where(Conversation.id == request.conversation_id)
    turn = database.scalar(
        (turn_query.with_for_update() if lock else turn_query).execution_options(
            populate_existing=True
        )
    )
    conversation = database.scalar(
        (conversation_query.with_for_update() if lock else conversation_query).execution_options(
            populate_existing=True
        )
    )
    if (
        conversation is None
        or conversation.user_id != request.owner_id
        or turn is None
        or turn.conversation_id != request.conversation_id
        or turn.user_message_id != request.before_message_id
        or turn.status != "running"
        or conversation.current_turn_id != request.turn_id
    ):
        raise ProfileSourceInvalid


def _lock_state(database: Session, owner: str, revision: int) -> UserProfileState:
    """锁真实账号保证首次状态行创建与后续CAS串行；不依赖进程内锁。"""
    account = database.scalar(
        select(UserAccount)
        .where(UserAccount.id == owner, UserAccount.is_active.is_(True))
        .with_for_update()
    )
    if account is None:
        raise ProfileSourceInvalid
    state = database.scalar(
        select(UserProfileState).where(UserProfileState.owner_id == owner).with_for_update()
    )
    if (state.revision if state else 0) != revision:
        raise ProfileConflict
    if state is None:
        state = UserProfileState(owner_id=owner, revision=0)
        database.add(state)
    return state


def _snapshot(database: Session, owner: str) -> ProfileSnapshot:
    """构造有界字段快照；ORM对象不得逃离Session。"""
    state = database.get(UserProfileState, owner)
    rows = database.scalars(
        select(UserProfileField)
        .where(UserProfileField.owner_id == owner)
        .order_by(UserProfileField.field_key)
    ).all()
    return ProfileSnapshot(
        state.revision if state else 0,
        tuple(
            ProfileItem(
                x.field_key,
                x.value,
                x.origin,
                x.value is None,
                x.source_conversation_id,
                x.source_message_id,
                x.evidence,
                x.updated_at.replace(tzinfo=UTC) if x.updated_at.tzinfo is None else x.updated_at,
            )
            for x in rows
        ),
    )
