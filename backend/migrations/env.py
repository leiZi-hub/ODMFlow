"""数据库迁移环境。

用途：
    从 ODMFLOW_DATABASE_URL 读取目标库，并执行显式 Alembic 版本迁移。

边界：
    不创建账号，不从仓库读取真实凭证，也不在导入应用模块时连接数据库。
"""

import os

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from odmflow.after_sales import models as after_sales_models  # noqa: F401
from odmflow.business_actions import models as action_models  # noqa: F401
from odmflow.conversations import models as conversation_models  # noqa: F401
from odmflow.identity import models as identity_models  # noqa: F401
from odmflow.orders import models as order_models  # noqa: F401
from odmflow.persistence import Base
from odmflow.profiles import models as profile_models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """使用显式配置的数据库连接执行版本迁移。"""

    database_url = os.environ.get("ODMFLOW_DATABASE_URL")
    if not database_url:
        raise RuntimeError("ODMFLOW_DATABASE_URL is required for migrations")
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations_online()
