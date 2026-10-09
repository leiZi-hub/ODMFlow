"""用途：售后安全只读契约；边界：不携带账号归属字段或Agent状态。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class AfterSalesView(BaseModel):
    """本人受理记录；submitted不是批准退换。"""

    model_config = ConfigDict(frozen=True)
    application_no: str
    order_no: str
    symptom: str
    occurred_at: str
    reproduction: str
    handling: str
    device_identifier: str | None
    status: Literal["submitted"] = "submitted"
    created_at: datetime
    simulated: Literal[True] = True


class AfterSalesList(BaseModel):
    """最多十条本人结果。"""

    items: tuple[AfterSalesView, ...] = ()
    has_more: bool = False


class AfterSalesLookup(BaseModel):
    """越权与无结果统一not_found。"""

    code: Literal["ok", "not_found"]
    application: AfterSalesView | None = None
