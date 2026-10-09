"""用途：以owner+目标条件读取本人订单。边界：短Session，不向模型开放SQL/跨用户查询。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from .domain import (
    OrderList,
    OrderLookup,
    OrderReadUnavailable,
    OrderStatus,
    OrderView,
    ProgressView,
)
from .models import Order, OrderProgressEvent


def is_transient_read_error(error: Exception) -> bool:
    """仅明确断连错误允许一次重试；认证、缺表及未知错误不重试。"""
    if not isinstance(error, DBAPIError):
        return False
    code = error.orig.args[0] if error.orig is not None and error.orig.args else None
    if code in (1045, 1049, 1146):
        return False
    return error.connection_invalidated or code in (2006, 2013)


def _view(order: Order) -> OrderView:
    """过滤ORM身份及开发标记，构造安全结果。"""
    return OrderView(
        order_no=order.order_no,
        product_model=order.product_model,
        quantity=order.quantity,
        target_market=order.target_market,
        configuration_summary=order.configuration_summary,
        status=OrderStatus(order.status),
        created_at=order.created_at.replace(tzinfo=UTC)
        if order.created_at.tzinfo is None
        else order.created_at,
        updated_at=order.updated_at.replace(tzinfo=UTC)
        if order.updated_at.tzinfo is None
        else order.updated_at,
    )


class SqlOrderRepository:
    """固定有界授权查询，不在模型等待期间持有Session。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """保存短会话工厂，不连接数据库。"""
        self.sessions = sessions

    def list_orders(self, owner_id: str, status: OrderStatus | None = None) -> OrderList:
        """在短Session内取最近11条判分页。

        Args:
            owner_id: 可信用户标识，始终作为查询条件。
            status: 可选状态过滤。
        Returns:
            最多十条本人订单，按创建时间及ID降序稳定排序。
        Raises:
            OrderReadUnavailable: 数据库失败；不暴露SQL与凭证。
        """
        try:
            with self.sessions() as session:
                statement = select(Order).where(Order.owner_id == owner_id)
                if status is not None:
                    statement = statement.where(Order.status == status.value)
                rows = session.scalars(
                    statement.order_by(Order.created_at.desc(), Order.id.desc()).limit(11)
                ).all()
                return OrderList(
                    items=tuple(_view(row) for row in rows[:10]),
                    has_more=len(rows) > 10,
                    queried_at=datetime.now(UTC),
                )
        except SQLAlchemyError as error:
            raise OrderReadUnavailable(is_transient_read_error(error)) from None

    def get_order(self, owner_id: str, order_no: str) -> OrderLookup:
        """先本人标识和编号查询，再读其最近进度。

        Args:
            owner_id: 可信用户标识，不可由模型覆盖。
            order_no: 已校验的目标订单号。
        Returns:
            本人详情和最近十条升序进度；越权与不存在统一not_found。
        Raises:
            OrderReadUnavailable: 已结束的数据库查询失败。
        """
        try:
            with self.sessions() as session:
                row = session.scalar(
                    select(Order).where(Order.owner_id == owner_id, Order.order_no == order_no)
                )
                if row is None:
                    return OrderLookup(code="not_found", queried_at=datetime.now(UTC))
                progress = session.scalars(
                    select(OrderProgressEvent)
                    .where(OrderProgressEvent.order_id == row.id)
                    .order_by(OrderProgressEvent.occurred_at.desc(), OrderProgressEvent.id.desc())
                    .limit(11)
                ).all()
                return OrderLookup(
                    code="ok",
                    order=_view(row),
                    has_more=len(progress) > 10,
                    progress=tuple(
                        ProgressView(
                            status=OrderStatus(item.status),
                            description=item.description,
                            occurred_at=item.occurred_at.replace(tzinfo=UTC)
                            if item.occurred_at.tzinfo is None
                            else item.occurred_at,
                        )
                        for item in reversed(progress[:10])
                    ),
                    queried_at=datetime.now(UTC),
                )
        except SQLAlchemyError as error:
            raise OrderReadUnavailable(is_transient_read_error(error)) from None
