"""私人对话查询 HTTP 入口；只读取当前登录账号的会话列表与历史消息。"""

from dataclasses import asdict
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from starlette.concurrency import run_in_threadpool

from odmflow.identity.dependencies import get_authenticated_principal
from odmflow.identity.domain import AuthenticatedPrincipal

from .application import ConversationService
from .domain import ConversationNotFound
from .presentation import message_projection, operation_projection

router = APIRouter(prefix="/conversations", tags=["conversations"])


def _service(request: Request) -> ConversationService:
    """从应用组合层取得私人对话服务。"""

    service: ConversationService | None = request.app.state.conversation_service
    if service is None:
        raise HTTPException(status_code=503, detail="Conversation storage unavailable")
    return service


@router.get("")
async def list_conversations(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> object:
    """按当前 Cookie 身份返回最近私人对话。"""

    page = await run_in_threadpool(
        _service(request).list_conversations, principal.user_id, limit, offset
    )
    return jsonable_encoder(asdict(page))


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    before_id: Annotated[int | None, Query(gt=0)] = None,
) -> object:
    """只允许所属账号按 ID 升序读取一页消息。"""

    try:
        page = await run_in_threadpool(
            _service(request).list_messages,
            principal.user_id,
            str(conversation_id),
            limit,
            before_id,
        )
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    detailed = request.app.state.trace_debug_enabled
    return jsonable_encoder(
        {
            "items": [
                {**message_projection(message, False), "details_available": detailed}
                for message in page.items
            ],
            "next_before_id": page.next_before_id,
        }
    )


@router.get("/{conversation_id}/turns/{turn_id}/operations")
async def list_turn_operations(
    conversation_id: UUID,
    turn_id: UUID,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
) -> object:
    """读取本人轮次操作，服务端开启调试时返回完整详细快照。

    Args:
        conversation_id: 查询对话。
        turn_id: 必须属于该对话的轮次。
        request: 取得组合根服务及调试权限。
        principal: Cookie确认的身份，不能由模型自报。
    Returns:
        安全投影的操作列表及是否允许详细查看。
    """
    try:
        rows = await run_in_threadpool(
            _service(request).list_operations,
            principal.user_id,
            str(conversation_id),
            str(turn_id),
        )
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    detailed = request.app.state.trace_debug_enabled
    return jsonable_encoder(
        {
            "items": [operation_projection(row, detailed) for row in rows],
            "details_available": detailed,
        }
    )
