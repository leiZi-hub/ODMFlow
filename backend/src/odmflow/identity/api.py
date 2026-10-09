"""身份 HTTP 接口。

用途：
    处理当前登录身份相关的 HTTP 请求。

边界：
    不在路由中定义密码校验或数据库访问规则。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .application import AccountAlreadyExists, InvalidCsrfToken
from .dependencies import (
    check_request_origin,
    get_auth_service,
    get_authenticated_principal,
    get_session_token,
)
from .domain import AuthenticatedPrincipal

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """登录提交的数据，不接受身份自报字段。"""

    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    password: str = Field(min_length=1)


class RegisterRequest(BaseModel):
    """公开注册输入，只接受用户名和原始口令。"""

    model_config = ConfigDict(extra="forbid")

    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    password: str = Field(min_length=12)

    @field_validator("username")
    @classmethod
    def validate_normalized_length(cls, username: str) -> str:
        """防止 casefold 扩展后超出数据库用户名长度。"""

        if len(username.casefold()) > 120:
            raise ValueError("username exceeds 120 characters after normalization")
        return username


class RegisteredAccountResponse(BaseModel):
    """返回新账号标识，不签发登录 Cookie。"""

    user_id: str
    username: str


class CurrentIdentityResponse(BaseModel):
    """向前端公开的当前用户身份，不包含任何令牌或密码。"""

    user_id: str
    username: str


class CsrfResponse(BaseModel):
    """返回当前登录会话的一次新 CSRF token。"""

    csrf_token: str


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, request: Request) -> RegisteredAccountResponse:
    """校验同源请求并创建本地账号，不自动登录。"""

    service = get_auth_service(request)
    check_request_origin(request, service.configuration)
    try:
        account = service.register(payload.username, payload.password)
    except AccountAlreadyExists as error:
        raise HTTPException(status_code=409, detail="Username already exists") from error
    return RegisteredAccountResponse(user_id=account.user_id, username=account.username)


@router.post("/login", status_code=204)
def login(payload: LoginRequest, request: Request, response: Response) -> None:
    """校验本地账号并设置不透明会话 Cookie。"""

    service = get_auth_service(request)
    check_request_origin(request, service.configuration)
    token = service.login(payload.username, payload.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    response.set_cookie(
        key=service.configuration.cookie_name,
        value=token,
        httponly=True,
        secure=service.configuration.mode == "production",
        samesite="strict",
        path="/",
        max_age=int(service.configuration.lifetime.total_seconds()),
    )


@router.get("/me")
def get_current_identity(
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
) -> CurrentIdentityResponse:
    """从服务端有效会话返回当前用户，而非接受客户端指定用户。"""

    return CurrentIdentityResponse(
        user_id=principal.user_id,
        username=principal.username,
    )


@router.get("/csrf")
def get_csrf(request: Request) -> CsrfResponse:
    """为当前有效会话签发并轮换 CSRF token。"""

    service = get_auth_service(request)
    token = get_session_token(request, service)
    csrf_token = service.rotate_csrf(token)
    if csrf_token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return CsrfResponse(csrf_token=csrf_token)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None),
) -> None:
    """校验 CSRF 后撤销服务端会话并清除浏览器 Cookie。"""

    service = get_auth_service(request)
    token = get_session_token(request, service)
    check_request_origin(request, service.configuration)
    try:
        revoked = service.logout(token, x_csrf_token)
    except InvalidCsrfToken as error:
        raise HTTPException(status_code=403, detail="Invalid CSRF token") from error
    if not revoked:
        raise HTTPException(status_code=401, detail="Not authenticated")
    response.delete_cookie(key=service.configuration.cookie_name, path="/")
