"""系统健康检查接口。

用途：
    提供不依赖业务数据和外部服务的基础存活检查。

边界：
    不判断数据库、缓存、模型 API 等依赖的就绪状态。
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """表示基础存活检查的稳定响应结构。"""

    status: Literal["ok"]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """返回当前进程能够处理请求的存活状态。"""

    return HealthResponse(status="ok")
