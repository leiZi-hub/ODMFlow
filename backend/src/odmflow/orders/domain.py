"""用途：订单状态和安全只读结果契约。边界：不授予身份或执行SQL。"""

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class OrderStatus(StrEnum):
    """模拟订单状态；只读阶段不允许Agent改变。"""

    PENDING_REVIEW = "pending_review"
    IN_PRODUCTION = "in_production"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class OrderView(BaseModel):
    """本人订单公开字段，不含owner或开发批次。"""

    model_config = ConfigDict(frozen=True)
    order_no: str
    product_model: str
    quantity: int
    target_market: str
    configuration_summary: str
    status: OrderStatus
    created_at: datetime
    updated_at: datetime


class ProgressView(BaseModel):
    """模拟状态进度，不代表真实生产或物流。"""

    model_config = ConfigDict(frozen=True)
    status: OrderStatus
    description: str
    occurred_at: datetime


class OrderList(BaseModel):
    """最近最多十笔，has_more避免把分页结果称全量。"""

    model_config = ConfigDict(frozen=True)
    items: tuple[OrderView, ...] = ()
    has_more: bool = False
    queried_at: datetime
    simulated: Literal[True] = True


class OrderLookup(BaseModel):
    """本人详情或统一查无结果，不透露订单是否属于其他账号。"""

    model_config = ConfigDict(frozen=True)
    code: Literal["ok", "not_found"]
    order: OrderView | None = None
    progress: tuple[ProgressView, ...] = ()
    has_more: bool = False
    queried_at: datetime
    simulated: Literal[True] = True


class OrderReadUnavailable(Exception):
    """下游已结束的读错误；是否瞬时由仓储分类，不含原始连接信息。"""

    def __init__(self, retryable: bool = False) -> None:
        """保存受控分类，默认未知故障不可重试。"""
        super().__init__("order_read_unavailable")
        self.retryable = retryable
