"""用途：确认事务内创建模拟订单；边界：不独立提交、不接受LLM身份、不涉及付款。"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from odmflow.business_actions.domain import ActionReceipt, OrderApplication

from .models import Order, OrderProgressEvent


def submit_order(
    session: Session, owner_id: str, action_id: str, parameters: OrderApplication, now: datetime
) -> ActionReceipt:
    """在已授权短事务中插入订单与进度；唯一source_action_id防重复。"""
    number = "OF-" + uuid4().hex.upper()
    row = Order(
        id=uuid4().hex,
        order_no=number,
        owner_id=owner_id,
        **parameters.model_dump(),
        status="pending_review",
        source_action_id=action_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    session.add(
        OrderProgressEvent(
            id=uuid4().hex,
            order_id=row.id,
            status="pending_review",
            description="模拟订单申请已受理，等待审核；不涉及真实支付。",
            occurred_at=now,
        )
    )
    return ActionReceipt(business_no=number, status="pending_review")
