"""用途：本人售后读仓储及事务内受理；边界：不运行模型，不独立确认。"""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from odmflow.business_actions.domain import ActionReceipt, AfterSalesApplication
from odmflow.orders.models import Order

from .domain import AfterSalesList, AfterSalesLookup, AfterSalesView
from .models import AfterSalesEvent, AfterSalesRequest


def submit_after_sales(
    session: Session,
    owner_id: str,
    action_id: str,
    order_id: str,
    parameters: AfterSalesApplication,
    now: datetime,
) -> ActionReceipt:
    """在调用方已锁定并验证订单的事务内写入意向及事件，不自行commit。"""
    number = "AS-" + uuid4().hex.upper()
    values = parameters.model_dump(exclude={"order_no"})
    row = AfterSalesRequest(
        id=uuid4().hex,
        application_no=number,
        owner_id=owner_id,
        order_id=order_id,
        source_action_id=action_id,
        **values,
        status="submitted",
        created_at=now,
    )
    session.add(row)
    session.flush()
    session.add(
        AfterSalesEvent(id=uuid4().hex, request_id=row.id, status="submitted", occurred_at=now)
    )
    return ActionReceipt(business_no=number, status="submitted")


def _view(row: AfterSalesRequest, number: str) -> AfterSalesView:
    """投影安全字段并规范SQLite返回的UTC时间。"""
    return AfterSalesView(
        application_no=row.application_no,
        order_no=number,
        symptom=row.symptom,
        occurred_at=row.occurred_at,
        reproduction=row.reproduction,
        handling=row.handling,
        device_identifier=row.device_identifier,
        created_at=row.created_at.replace(tzinfo=UTC),
    )


class SqlAfterSalesRepository:
    """SQL查询始终包含可信owner，查询不依赖某个对话。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """保存短事务工厂，不立即连接。"""
        self.sessions = sessions

    def list(self, owner_id: str) -> AfterSalesList:
        """返回最多十条本人受理记录和has_more。"""
        with self.sessions() as session:
            rows = session.execute(
                select(AfterSalesRequest, Order.order_no)
                .join(Order, Order.id == AfterSalesRequest.order_id)
                .where(AfterSalesRequest.owner_id == owner_id, Order.owner_id == owner_id)
                .order_by(AfterSalesRequest.created_at.desc(), AfterSalesRequest.id.desc())
                .limit(11)
            ).all()
            return AfterSalesList(
                items=tuple(_view(row, no) for row, no in rows[:10]), has_more=len(rows) > 10
            )

    def get(self, owner_id: str, application_no: str) -> AfterSalesLookup:
        """按明确编号查询本人记录，越权与不存在均查无。"""
        with self.sessions() as session:
            result = session.execute(
                select(AfterSalesRequest, Order.order_no)
                .join(Order, Order.id == AfterSalesRequest.order_id)
                .where(
                    AfterSalesRequest.owner_id == owner_id,
                    Order.owner_id == owner_id,
                    AfterSalesRequest.application_no == application_no,
                )
            ).first()
            return (
                AfterSalesLookup(code="not_found")
                if result is None
                else AfterSalesLookup(code="ok", application=_view(result[0], result[1]))
            )
