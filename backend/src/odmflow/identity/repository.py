"""身份模块的 SQLAlchemy 仓储适配器。

用途：
    将应用层账号和会话端口映射到数据库表，并限定事务边界。

边界：
    不决定 HTTP 状态码、密码是否正确或具体业务资源的访问权。
"""

import sqlite3
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .domain import AccountSnapshot, LoginSessionSnapshot, NewAccount, NewLoginSession
from .models import AuthSession, UserAccount


class SqlIdentityRepository:
    """使用短生命周期数据库会话实现身份持久化端口。"""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        """保存会话工厂；构造仓储时不连接数据库。"""

        self._sessions = sessions

    def account_by_username(self, username: str) -> AccountSnapshot | None:
        """按用户名读取账号快照。"""

        with self._sessions() as database:
            account = database.scalar(select(UserAccount).where(UserAccount.username == username))
            return _account_snapshot(account)

    def account_by_id(self, user_id: str) -> AccountSnapshot | None:
        """按账号标识读取快照。"""

        with self._sessions() as database:
            return _account_snapshot(database.get(UserAccount, user_id))

    def create_account(self, new_account: NewAccount) -> bool:
        """保存账号；仅用户名唯一冲突返回 False，其他数据库错误上抛。"""

        try:
            with self._sessions.begin() as database:
                database.add(
                    UserAccount(
                        id=new_account.user_id,
                        username=new_account.username,
                        password_hash=new_account.password_hash,
                        is_active=True,
                    )
                )
        except IntegrityError as error:
            if _username_unique_conflict(error):
                return False
            raise
        return True

    def create_session(self, new_session: NewLoginSession) -> None:
        """在独立事务中保存只包含 token 摘要的会话。"""

        with self._sessions.begin() as database:
            database.add(
                AuthSession(
                    id=new_session.session_id,
                    user_id=new_session.user_id,
                    token_digest=new_session.token_digest,
                    csrf_digest=None,
                    created_at=new_session.created_at,
                    expires_at=new_session.expires_at,
                    revoked_at=None,
                )
            )

    def session_by_token_digest(self, token_digest: str) -> LoginSessionSnapshot | None:
        """按 token 摘要读取会话，不返回原始 token。"""

        with self._sessions() as database:
            login_session = database.scalar(
                select(AuthSession).where(AuthSession.token_digest == token_digest)
            )
            if login_session is None:
                return None
            return LoginSessionSnapshot(
                session_id=login_session.id,
                user_id=login_session.user_id,
                csrf_digest=login_session.csrf_digest,
                expires_at=login_session.expires_at,
                revoked_at=login_session.revoked_at,
            )

    def replace_csrf(self, session_id: str, digest: str) -> bool:
        """在会话未撤销时原子替换 CSRF 摘要。"""

        with self._sessions.begin() as database:
            result = database.execute(
                update(AuthSession)
                .where(AuthSession.id == session_id, AuthSession.revoked_at.is_(None))
                .values(csrf_digest=digest)
            )
            return bool(cast(CursorResult[Any], result).rowcount)

    def revoke_session(self, session_id: str, csrf_digest: str, when: datetime) -> bool:
        """在摘要仍匹配时原子撤销，避免并发轮换后使用旧 token。"""

        with self._sessions.begin() as database:
            result = database.execute(
                update(AuthSession)
                .where(
                    AuthSession.id == session_id,
                    AuthSession.csrf_digest == csrf_digest,
                    AuthSession.revoked_at.is_(None),
                )
                .values(revoked_at=when)
            )
            return bool(cast(CursorResult[Any], result).rowcount)


def _username_unique_conflict(error: IntegrityError) -> bool:
    """只识别账号名唯一约束，避免把其他完整性错误伪装成重名。"""

    original = error.orig
    if original is None:
        return False
    if isinstance(original, sqlite3.IntegrityError):
        return str(original) == "UNIQUE constraint failed: user_account.username"
    arguments = list(original.args)
    return (
        len(arguments) >= 2
        and arguments[0] == 1062
        and "uq_user_account_username" in str(arguments[1])
    )


def _account_snapshot(account: UserAccount | None) -> AccountSnapshot | None:
    """把数据库对象转换成脱离会话的认证数据。"""

    if account is None:
        return None
    return AccountSnapshot(
        user_id=account.id,
        username=account.username,
        password_hash=account.password_hash,
        is_active=account.is_active,
    )
