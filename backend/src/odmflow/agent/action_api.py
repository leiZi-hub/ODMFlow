"""用途：本人确认卡的HTTP入口；边界：身份仅Session，写请求仅revision，没有工具确认入口。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from odmflow.business_actions.domain import ActionConflict, ActionNotFound, ActionPage, ActionView
from odmflow.identity.dependencies import (
    get_authenticated_principal,
    get_authorized_write_principal,
)
from odmflow.identity.domain import AuthenticatedPrincipal

from .approvals.service import ApprovalService, ApprovalUnavailable

router = APIRouter(prefix="/agent/actions", tags=["agent-applications"])
ReadPrincipal = Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)]
WritePrincipal = Annotated[AuthenticatedPrincipal, Depends(get_authorized_write_principal)]


class ActionDecision(BaseModel):
    """只核对服务器版本，不接受客户端重写参数、身份或图ID。"""

    model_config = ConfigDict(extra="forbid")
    revision: Annotated[int, Field(strict=True, ge=1)]


def _service(request: Request) -> ApprovalService:
    """缺少数据库/策略禁用时返回明确503，不默默退化为直接业务写。"""
    service: ApprovalService | None = request.app.state.approval_service
    if service is None:
        raise HTTPException(503, "Applications unavailable")
    return service


@router.get("")
async def list_actions(
    request: Request,
    principal: ReadPrincipal,
    conversation_id: UUID,
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ActionPage:
    """查询本人指定对话的确认卡，有界分页；跨用户统一404。"""
    try:
        return await _service(request).list(principal.user_id, str(conversation_id), limit, offset)
    except ActionNotFound as error:
        raise HTTPException(404, "Action not found") from error


@router.get("/{action_id}")
async def get_action(request: Request, principal: ReadPrincipal, action_id: UUID) -> ActionView:
    """结果不明时先查询权威状态，不触发执行或模型调用。"""
    try:
        return await _service(request).get(principal.user_id, str(action_id))
    except ActionNotFound as error:
        raise HTTPException(404, "Action not found") from error


async def _decide(
    request: Request,
    principal: AuthenticatedPrincipal,
    action_id: UUID,
    payload: ActionDecision,
    confirmed: bool,
) -> ActionView:
    """Origin/CSRF/Session验证后才恢复服务器派生写图；未知结果503后必须GET。"""
    try:
        return await _service(request).decide(
            principal.user_id, str(action_id), payload.revision, confirmed
        )
    except ActionNotFound as error:
        raise HTTPException(404, "Action not found") from error
    except ActionConflict as error:
        raise HTTPException(409, "Action changed; reload before continuing") from error
    except ApprovalUnavailable as error:
        raise HTTPException(
            503, "Application result unknown; query status before continuing"
        ) from error


@router.post("/{action_id}/confirm")
async def confirm_action(
    request: Request, principal: WritePrincipal, action_id: UUID, payload: ActionDecision
) -> ActionView:
    """结构化明确确认；不从自然语言消息、记忆或工具文本推断授权。"""
    return await _decide(request, principal, action_id, payload, True)


@router.post("/{action_id}/cancel")
async def cancel_action(
    request: Request, principal: WritePrincipal, action_id: UUID, payload: ActionDecision
) -> ActionView:
    """取消预览，已成功动作不能改成取消。"""
    return await _decide(request, principal, action_id, payload, False)
