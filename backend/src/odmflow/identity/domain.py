"""已认证主体的稳定数据契约。

用途：
    表示后端会话校验后得到的当前用户身份。

边界：
    不从 HTTP 参数或模型输出直接构造可信主体，不判断具体业务资源权限。
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """表示已验证的登录用户，而非业务资源的自动授权凭据。"""

    user_id: str
    username: str


@dataclass(frozen=True)
class AccountSnapshot:
    """供认证用例读取的账号快照，不暴露 ORM 会话。"""

    user_id: str
    username: str
    password_hash: str
    is_active: bool


@dataclass(frozen=True)
class NewAccount:
    """待持久化的本地账号，只携带 Argon2 口令哈希。"""

    user_id: str
    username: str
    password_hash: str


@dataclass(frozen=True)
class RegisteredAccount:
    """注册成功后可公开的账号标识，不含口令或会话。"""

    user_id: str
    username: str


@dataclass(frozen=True)
class LoginSessionSnapshot:
    """供会话校验用例读取的服务端状态快照。"""

    session_id: str
    user_id: str
    csrf_digest: str | None
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class NewLoginSession:
    """待持久化的新登录会话，不包含原始 Cookie token。"""

    session_id: str
    user_id: str
    token_digest: str
    created_at: datetime
    expires_at: datetime
