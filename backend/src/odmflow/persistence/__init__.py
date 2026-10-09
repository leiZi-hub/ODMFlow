"""共享持久化公开入口。

用途：导出共用映射基类与数据库会话工厂。
边界：导入不连接数据库或加载业务表。
"""

from .database import Base, build_database_sessions

__all__ = ["Base", "build_database_sessions"]
