"""身份模块公开入口。

用途：
    向应用组合层暴露身份 HTTP 路由。

边界：
    不在导入时连接数据库或创建用户。
"""

from .api import router

__all__ = ["router"]
