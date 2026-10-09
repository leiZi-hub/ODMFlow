"""身份与登录会话用例。

用途：
    校验账号密码、签发与撤销服务端会话，并构造已认证主体。

边界：
    不处理 Cookie/HTTP，不判断询盘、草稿或订单的资源级权限。
"""

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .domain import (
    AuthenticatedPrincipal,
    LoginSessionSnapshot,
    NewAccount,
    NewLoginSession,
    RegisteredAccount,
)
from .ports import IdentityRepository


@dataclass(frozen=True)
class AuthConfiguration:
    """定义本地或 HTTPS 部署下的会话 Cookie 与同源边界。"""

    app_origin: str = "http://127.0.0.1:8000"
    mode: str = "local"
    cookie_name: str = "odmflow_session"
    lifetime: timedelta = timedelta(hours=8)

    def __post_init__(self) -> None:
        """拒绝未声明安全来源的生产配置。"""

        if self.mode not in {"local", "production"}:
            raise ValueError("ODMFLOW_MODE must be local or production")
        parsed_origin = urlsplit(self.app_origin)
        if self.mode == "local" and (
            parsed_origin.scheme != "http"
            or parsed_origin.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.path not in {"", "/"}
        ):
            raise ValueError("local app origin must use HTTP loopback")
        if self.mode == "production" and not self.app_origin.startswith("https://"):
            raise ValueError("production app origin must use HTTPS")


class InvalidCsrfToken(Exception):
    """表示当前会话的 CSRF token 缺失或不匹配。"""


class AccountAlreadyExists(Exception):
    """表示规范化后的用户名已经存在。"""


class AuthService:
    """执行账号认证与服务端会话生命周期，不处理 HTTP 表示。"""

    def __init__(
        self,
        repository: IdentityRepository,
        configuration: AuthConfiguration,
    ) -> None:
        """保存持久化端口与配置，不立即连接数据库。"""

        self._repository = repository
        self.configuration = configuration
        self._password_hasher = PasswordHasher()

    def register(self, username: str, password: str) -> RegisteredAccount:
        """校验并规范化账号字段，只保存口令哈希，不创建登录会话。

        Raises:
            ValueError: 用户名或口令不符合注册约束。
            AccountAlreadyExists: 规范化后的用户名已存在。
        """

        normalized_username = username.strip().casefold()
        if not normalized_username or len(normalized_username) > 120:
            raise ValueError("username must contain 1 to 120 characters")
        if len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        new_account = NewAccount(
            user_id=uuid4().hex,
            username=normalized_username,
            password_hash=self._password_hasher.hash(password),
        )
        if not self._repository.create_account(new_account):
            raise AccountAlreadyExists
        return RegisteredAccount(
            user_id=new_account.user_id,
            username=new_account.username,
        )

    def login(self, username: str, password: str) -> str | None:
        """校验账号并签发不透明 token；失败时不暴露具体原因。"""

        normalized_username = username.strip().casefold()
        account = self._repository.account_by_username(normalized_username)
        if account is None or not account.is_active:
            return None
        try:
            self._password_hasher.verify(account.password_hash, password)
        except VerifyMismatchError, VerificationError, InvalidHashError:
            return None

        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        self._repository.create_session(
            NewLoginSession(
                session_id=uuid4().hex,
                user_id=account.user_id,
                token_digest=_digest(token),
                created_at=now,
                expires_at=now + self.configuration.lifetime,
            )
        )
        return token

    def principal(self, token: str) -> AuthenticatedPrincipal | None:
        """从有效服务端会话取得当前主体，拒绝过期或已撤销会话。"""

        active_session = self._find_active_session(token)
        if active_session is None:
            return None
        account = self._repository.account_by_id(active_session.user_id)
        if account is None or not account.is_active:
            return None
        return AuthenticatedPrincipal(
            user_id=account.user_id,
            username=account.username,
        )

    def rotate_csrf(self, token: str) -> str | None:
        """为有效会话签发新 CSRF token，并仅保存摘要。"""

        active_session = self._find_active_session(token)
        if active_session is None:
            return None
        csrf_token = secrets.token_urlsafe(32)
        if not self._repository.replace_csrf(active_session.session_id, _digest(csrf_token)):
            return None
        return csrf_token

    def validate_csrf(self, token: str, csrf_token: str | None) -> bool:
        """验证有效会话的写请求 CSRF token，不撤销或轮换会话。

        Args:
            token: 浏览器 Cookie 中的不透明登录 token。
            csrf_token: 浏览器请求头提交的 CSRF token。

        Returns:
            会话是否仍然有效；无效 CSRF 则抛出 InvalidCsrfToken。
        """

        active_session = self._find_active_session(token)
        if active_session is None:
            return False
        if (
            csrf_token is None
            or active_session.csrf_digest is None
            or not hmac.compare_digest(active_session.csrf_digest, _digest(csrf_token))
        ):
            raise InvalidCsrfToken
        return True

    def logout(self, token: str, csrf_token: str | None) -> bool:
        """撤销有效会话；CSRF 无效时不改变会话。"""

        active_session = self._find_active_session(token)
        if active_session is None:
            return False
        if (
            csrf_token is None
            or active_session.csrf_digest is None
            or not hmac.compare_digest(active_session.csrf_digest, _digest(csrf_token))
        ):
            raise InvalidCsrfToken
        return self._repository.revoke_session(
            active_session.session_id,
            active_session.csrf_digest,
            datetime.now(UTC),
        )

    def _find_active_session(self, token: str) -> LoginSessionSnapshot | None:
        """读取有效会话，并再次确认账号未被停用。"""

        active_session = self._repository.session_by_token_digest(_digest(token))
        if active_session is None or active_session.revoked_at is not None:
            return None
        expires_at = active_session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return None
        account = self._repository.account_by_id(active_session.user_id)
        if account is None or not account.is_active:
            return None
        return active_session


def _digest(value: str) -> str:
    """为不透明会话值生成可查询且不可逆的固定长度摘要。"""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()
