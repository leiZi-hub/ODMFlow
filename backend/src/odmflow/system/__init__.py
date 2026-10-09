"""系统级通用能力包。

用途：
    容纳健康检查等独立于 ODM 业务流程的系统接口。

边界：
    不包含询盘、Agent、知识库或销售业务逻辑。
"""

from .health import router

__all__ = ["router"]
