"""共享身份 HTTP 依赖。

用途：从服务端会话验证身份、Cookie、Origin 与写请求 CSRF。
边界：只用于 HTTP 适配；不接受客户端自报身份，不直接操作数据库。
"""

from fastapi import Header, HTTPException, Request

from .application import AuthConfiguration, AuthService, InvalidCsrfToken
from .domain import AuthenticatedPrincipal


def get_auth_service(request: Request) -> AuthService:
    """取出应用组合层注入的身份服务。

    Args:
        request: 当前 HTTP 请求，含应用状态。
    Returns:
        已组装的身份服务。
    Raises:
        HTTPException: 未配置身份存储时返回 503。
    """

    service: AuthService | None = request.app.state.auth_service
    if service is None:
        raise HTTPException(status_code=503, detail="Authentication storage unavailable")
    return service


def get_session_token(request: Request, service: AuthService) -> str:
    """从 Cookie 而非 URL 或模型参数取得会话 token。

    Args:
        request: 当前 HTTP 请求。
        service: 提供 Cookie 名称的身份服务。
    Returns:
        未验证的 Cookie token，仍须由身份服务验证。
    Raises:
        HTTPException: 缺少 Cookie 时返回 401。
    """

    cookie: str | None = request.cookies.get(service.configuration.cookie_name)
    if cookie is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return cookie


def check_request_origin(request: Request, configuration: AuthConfiguration) -> None:
    """拒绝缺失或不匹配的请求来源。

    Args:
        request: 待检查的 HTTP 请求。
        configuration: 服务端允许的来源配置。
    Returns:
        无；校验通过后继续执行。
    Raises:
        HTTPException: 来源不匹配时返回 403。
    """

    origin = request.headers.get("origin")
    if origin != configuration.app_origin:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def get_authenticated_principal(request: Request) -> AuthenticatedPrincipal:
    """供业务路由复用的可信当前用户依赖，不接受客户端自报身份。

    Args:
        request: 携带服务端会话 Cookie 的请求。
    Returns:
        已验证的账号主体。
    Raises:
        HTTPException: 未配置存储返回 503；未登录或会话无效返回 401。
    """

    service = get_auth_service(request)
    token = get_session_token(request, service)
    principal = service.principal(token)
    if principal is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return principal


def get_authorized_write_principal(
    request: Request,
    x_csrf_token: str | None = Header(default=None),
) -> AuthenticatedPrincipal:
    """供需登录的写路由复用身份、同源和 CSRF 三重门禁。

    Args:
        request: 待验证的 HTTP 写请求。
        x_csrf_token: 请求头中的 CSRF token。
    Returns:
        通过身份、来源与 CSRF 校验的主体。
    Raises:
        HTTPException: 存储未配置返回 503；会话无效返回 401；来源或 CSRF 无效返回 403。
    """

    principal = get_authenticated_principal(request)
    service = get_auth_service(request)
    check_request_origin(request, service.configuration)
    token = get_session_token(request, service)
    try:
        valid = service.validate_csrf(token, x_csrf_token)
    except InvalidCsrfToken as error:
        raise HTTPException(status_code=403, detail="Invalid CSRF token") from error
    if not valid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return principal
