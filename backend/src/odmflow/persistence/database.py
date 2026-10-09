"""共享数据库基础设施。

用途：提供所有业务 ORM 共用的 Base 与 MySQL 会话工厂。
边界：不定义业务表、不执行迁移，构造工厂时不连接数据库。
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """项目共享的映射基类；不承载业务操作。"""


def build_database_sessions() -> sessionmaker[Session] | None:
    """从环境创建共享会话工厂。

    Returns:
        MySQL 会话工厂；未配置数据库时返回 None。
    Raises:
        ValueError: 配置不是现行支持的 mysql+pymysql 方言。
    """
    database_url = os.environ.get("ODMFLOW_DATABASE_URL")
    if not database_url:
        return None
    if not database_url.startswith("mysql+pymysql://"):
        raise ValueError("ODMFLOW_DATABASE_URL must use mysql+pymysql")
    return sessionmaker(create_engine(database_url, pool_pre_ping=True), expire_on_commit=False)
