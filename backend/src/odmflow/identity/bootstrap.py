"""身份模块的本地运行组装。

用途：
    从环境读取应用来源配置，注入共享数据库工厂，创建身份服务。

边界：
    不运行迁移或建立数据库连接；测试可直接注入隔离会话工厂。
"""

import os

from sqlalchemy.orm import Session, sessionmaker

from odmflow.persistence import build_database_sessions

from .application import AuthConfiguration, AuthService
from .repository import SqlIdentityRepository


def build_auth_service(session_factory: sessionmaker[Session] | None = None) -> AuthService | None:
    """创建身份服务；无数据库配置时保留健康接口并让身份接口返回 503。

    Args:
        session_factory: 测试注入的隔离数据库工厂；缺省时从环境读取 MySQL。

    Returns:
        已配置的身份服务；缺少数据库连接配置时为 None。

    Raises:
        ValueError: 生产来源或数据库方言配置不符合本地首版约束。
    """

    if session_factory is None:
        session_factory = build_database_sessions()
        if session_factory is None:
            return None
    mode = os.environ.get("ODMFLOW_MODE")
    if mode is None:
        raise ValueError("ODMFLOW_MODE must be explicitly set when authentication is enabled")
    configuration = AuthConfiguration(
        mode=mode,
        app_origin=os.environ.get("ODMFLOW_APP_ORIGIN", "http://127.0.0.1:8000"),
    )
    return AuthService(SqlIdentityRepository(session_factory), configuration)
