"""用途：预览与确认的事务门禁；边界：MySQL是权威，不等待用户/模型，不吞commit错误。"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from pydantic import JsonValue
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from odmflow.after_sales.repository import submit_after_sales
from odmflow.conversations.models import Conversation, ConversationTurn
from odmflow.conversations.receipt_writer import append_receipt
from odmflow.orders.models import Order
from odmflow.orders.submission import submit_order

from .domain import (
    ActionConflict,
    ActionKind,
    ActionNotFound,
    ActionPage,
    ActionReceipt,
    ActionStatus,
    ActionView,
    AfterSalesApplication,
    OrderApplication,
)
from .models import BusinessAction, BusinessActionAudit


def _utc(value: datetime) -> datetime:
    """将数据库无时区UTC映射规范化，避免时区混比。"""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _view(row: BusinessAction) -> ActionView:
    """返回安全快照，不暴露身份、目标内部ID或图运行标识。"""
    return ActionView(
        id=row.id,
        kind=cast(ActionKind, row.kind),
        status=cast(ActionStatus, row.status),
        revision=row.revision,
        conversation_id=row.conversation_id,
        turn_id=row.turn_id,
        parameters=cast(dict[str, JsonValue], json.loads(row.parameters_json)),
        expires_at=_utc(row.expires_at),
        result=ActionReceipt.model_validate(row.result) if row.result else None,
    )


def _owned(session: Session, owner: str, action_id: str, *, lock: bool = False) -> BusinessAction:
    """事务内按owner定位；锁仅覆盖本次确认，不覆盖人工等待。"""
    statement = select(BusinessAction).where(
        BusinessAction.id == action_id, BusinessAction.owner_id == owner
    )
    if lock:
        statement = statement.with_for_update()
    row = session.scalar(statement)
    if row is None:
        raise ActionNotFound()
    return row


def _audit(session: Session, row: BusinessAction, now: datetime) -> None:
    """与状态同事务登记无敏感内容的审计事实。"""
    session.add(
        BusinessActionAudit(id=str(uuid4()), action_id=row.id, status=row.status, occurred_at=now)
    )


class SqlBusinessActionRepository:
    """数据库所有权/版本/CAS和唯一业务来源共同保证受控幂等。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """注入短事务工厂，不连接本机开发库。"""
        self.sessions = sessions

    def prepare(
        self, owner: str, conversation: str, turn: str, kind: str, snapshot: str, ttl: int
    ) -> ActionView:
        """来源轮锁串行化同轮预览；只保存参数，不建订单/售后。"""
        digest = hashlib.sha256(snapshot.encode()).hexdigest()
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            source = session.scalar(
                select(ConversationTurn)
                .join(Conversation, Conversation.id == ConversationTurn.conversation_id)
                .where(
                    ConversationTurn.id == turn,
                    Conversation.id == conversation,
                    Conversation.user_id == owner,
                )
                .with_for_update()
            )
            if source is None:
                raise ActionNotFound()
            previous = session.scalar(select(BusinessAction).where(BusinessAction.turn_id == turn))
            if previous is not None:
                if (
                    previous.owner_id != owner
                    or previous.kind != kind
                    or previous.parameter_digest != digest
                ):
                    raise ActionConflict("turn_already_has_preview")
                return _view(previous)
            target: Order | None = None
            if kind == "after_sales_application":
                params = AfterSalesApplication.model_validate_json(snapshot)
                target = session.scalar(
                    select(Order)
                    .where(Order.owner_id == owner, Order.order_no == params.order_no)
                    .with_for_update()
                )
                if target is None:
                    raise ActionNotFound()
                if target.status != "delivered":
                    raise ActionConflict("order_not_delivered")
            row = BusinessAction(
                id=str(uuid4()),
                owner_id=owner,
                conversation_id=conversation,
                turn_id=turn,
                kind=kind,
                status="pending_confirmation",
                revision=1,
                schema_version=1,
                parameters_json=snapshot,
                parameter_digest=digest,
                target_order_id=target.id if target else None,
                target_version=target.version if target else None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
            session.add(row)
            session.flush()
            _audit(session, row, now)
            return _view(row)

    def get(self, owner: str, action_id: str) -> ActionView:
        """查询本人动作；不信任图的参数或缓存结果。"""
        with self.sessions() as session:
            return _view(_owned(session, owner, action_id))

    def list(self, owner: str, conversation: str, limit: int, offset: int) -> ActionPage:
        """先核验本人对话，再返回稳定有限分页。"""
        with self.sessions() as session:
            if (
                session.scalar(
                    select(Conversation.id).where(
                        Conversation.id == conversation, Conversation.user_id == owner
                    )
                )
                is None
            ):
                raise ActionNotFound()
            rows = session.scalars(
                select(BusinessAction)
                .where(
                    BusinessAction.owner_id == owner, BusinessAction.conversation_id == conversation
                )
                .order_by(BusinessAction.created_at.desc(), BusinessAction.id.desc())
                .offset(offset)
                .limit(limit + 1)
            ).all()
            return ActionPage(
                items=tuple(_view(row) for row in rows[:limit]), has_more=len(rows) > limit
            )

    def decide(self, owner: str, action_id: str, revision: int, confirmed: bool) -> ActionView:
        """锁定动作并CAS，业务记录/结果/审计同事务；未知提交故障须GET核对。"""
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            row = _owned(session, owner, action_id, lock=True)
            if revision != row.revision:
                raise ActionConflict("revision_changed")
            if row.status != "pending_confirmation":
                if (row.status == "succeeded" and not confirmed) or (
                    row.status == "cancelled" and confirmed
                ):
                    raise ActionConflict("decision_changed")
                return _view(row)
            # MySQL行锁 + 条件更新；SQLite不具备MySQL行锁语义，但唯一键仍是最后防线。
            changed = session.execute(
                update(BusinessAction)
                .where(
                    BusinessAction.id == row.id,
                    BusinessAction.owner_id == owner,
                    BusinessAction.revision == revision,
                    BusinessAction.status == "pending_confirmation",
                )
                .values(updated_at=now)
            )
            if cast(CursorResult[tuple[object, ...]], changed).rowcount != 1:
                raise ActionConflict("action_changed")
            if _utc(row.expires_at) <= now:
                row.status = "expired"
            elif not confirmed:
                row.status = "cancelled"
            elif (
                row.schema_version != 1
                or hashlib.sha256(row.parameters_json.encode()).hexdigest() != row.parameter_digest
            ):
                row.status = "invalidated"
            else:
                self._execute(session, row, now)
            row.updated_at = now
            _audit(session, row, now)
            session.flush()
            return _view(row)

    def _execute(self, session: Session, row: BusinessAction, now: datetime) -> None:
        """仅供已锁定且确认的动作；事务内重验目标，不自行commit。"""
        receipt: ActionReceipt
        if row.kind == "order_application":
            params = OrderApplication.model_validate_json(row.parameters_json)
            receipt = submit_order(session, row.owner_id, row.id, params, now)
        elif row.kind == "after_sales_application":
            target = session.scalar(
                select(Order)
                .where(Order.id == row.target_order_id, Order.owner_id == row.owner_id)
                .with_for_update()
            )
            if (
                target is None
                or target.status != "delivered"
                or target.version != row.target_version
            ):
                row.status = "invalidated"
                return
            after = AfterSalesApplication.model_validate_json(row.parameters_json)
            receipt = submit_after_sales(session, row.owner_id, row.id, target.id, after, now)
        else:
            row.status = "invalidated"
            return
        row.status = "succeeded"
        row.result = receipt.model_dump()

    def save_receipt(self, owner: str, action_id: str) -> None:
        """单独幂等投影终态到消息；失败不能回滚已完成的业务确认事务。"""
        with self.sessions.begin() as session:
            row = _owned(session, owner, action_id, lock=True)
            if row.status == "pending_confirmation" or row.receipt_message_id is not None:
                return
            status = {
                "succeeded": "模拟申请已提交",
                "cancelled": "模拟申请已取消",
                "expired": "确认卡已过期，请重新发起申请",
                "invalidated": "条件已变化，请重新准备申请",
            }[row.status]
            receipt = ActionReceipt.model_validate(row.result) if row.result else None
            text = status + (
                f"。编号：{receipt.business_no}；状态：{receipt.status}。仅为模拟，受理不代表批准或支付。"
                if receipt
                else "。未创建业务记录。"
            )
            row.receipt_message_id = append_receipt(
                session, owner, row.conversation_id, text, datetime.now(UTC)
            )

    def terminal_before(self, cutoff: datetime) -> tuple[str, ...]:
        """维护入口获取最多100个超期终态ID；不返回/删除pending或业务记录。"""
        with self.sessions() as session:
            return tuple(
                session.scalars(
                    select(BusinessAction.id)
                    .where(
                        BusinessAction.status != "pending_confirmation",
                        BusinessAction.updated_at < cutoff,
                        BusinessAction.checkpoint_pruned_at.is_(None),
                    )
                    .order_by(BusinessAction.updated_at, BusinessAction.id)
                    .limit(100)
                )
            )

    def mark_checkpoint_pruned(self, action_id: str) -> None:
        """维护事务只标记已清理终态，避免前100条反复占队；不删业务或审计。"""
        with self.sessions.begin() as session:
            session.execute(
                update(BusinessAction)
                .where(
                    BusinessAction.id == action_id,
                    BusinessAction.status != "pending_confirmation",
                    BusinessAction.checkpoint_pruned_at.is_(None),
                )
                .values(checkpoint_pruned_at=datetime.now(UTC))
            )
