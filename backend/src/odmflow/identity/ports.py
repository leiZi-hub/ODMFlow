"""身份用例所需的持久化端口。

用途：
    定义认证用例读取账号、写入及撤销会话所需的最小接口。

边界：
    不指定 SQLAlchemy、MySQL 或 HTTP 的具体实现。
"""

from datetime import datetime
from typing import Protocol

from .domain import AccountSnapshot, LoginSessionSnapshot, NewAccount, NewLoginSession


class IdentityRepository(Protocol):
    """抽象账号和登录会话存储，供应用用例调用。"""

    def account_by_username(self, username: str) -> AccountSnapshot | None:
        """按规范化用户名读取账号。"""

    def account_by_id(self, user_id: str) -> AccountSnapshot | None:
        """按稳定标识读取账号。"""

    def create_account(self, new_account: NewAccount) -> bool:
        """持久化新账号；用户名冲突时返回 False。"""

    def create_session(self, new_session: NewLoginSession) -> None:
        """持久化只含令牌摘要的新会话。"""

    def session_by_token_digest(self, token_digest: str) -> LoginSessionSnapshot | None:
        """按令牌摘要读取会话快照。"""

    def replace_csrf(self, session_id: str, digest: str) -> bool:
        """仅在会话仍未撤销时替换 CSRF 摘要。"""

    def revoke_session(self, session_id: str, csrf_digest: str, when: datetime) -> bool:
        """仅在 CSRF 摘要仍匹配且会话未撤销时撤销。"""
