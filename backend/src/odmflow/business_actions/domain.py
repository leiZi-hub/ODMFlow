"""用途：模拟申请的不可变参数、预览与回执；边界：不执行SQL或Agent编排。"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)]
ActionKind = Literal["order_application", "after_sales_application"]
ActionStatus = Literal["pending_confirmation", "succeeded", "cancelled", "expired", "invalidated"]


class OrderApplication(BaseModel):
    """订单申请快照；不含价格、支付或用户身份。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    product_model: Literal["OF-T10", "OF-P6"]
    quantity: Annotated[int, Field(strict=True, gt=0, le=1000000)]
    target_market: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    configuration_summary: Text


class AfterSalesApplication(BaseModel):
    """售后受理意向；受理不代表批准换退、退款或完成维修。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    order_no: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    symptom: Text
    occurred_at: Text
    reproduction: Text
    handling: Literal["repair_consultation", "exchange_request", "return_request"]
    device_identifier: Annotated[str, StringConstraints(max_length=120)] | None = None


class ActionReceipt(BaseModel):
    """已提交事务产生的权威模拟编号，不由LLM生成。"""

    model_config = ConfigDict(frozen=True)
    business_no: str
    status: str
    simulated: Literal[True] = True


class ActionView(BaseModel):
    """本人可见确认卡；不暴露owner、图游标或连接信息。"""

    model_config = ConfigDict(frozen=True)
    id: str
    kind: ActionKind
    status: ActionStatus
    revision: int
    conversation_id: str
    turn_id: str
    parameters: dict[str, JsonValue]
    expires_at: datetime
    result: ActionReceipt | None = None
    simulated: Literal[True] = True


class ActionPage(BaseModel):
    """有界本人动作列表，不将单页结果视为全量。"""

    items: tuple[ActionView, ...] = ()
    has_more: bool = False


class ActionNotFound(Exception):
    """无资源与越权同义，避免泄露他人动作是否存在。"""


class ActionConflict(Exception):
    """参数、版本或决定冲突；客户端应重新读取权威结果。"""
