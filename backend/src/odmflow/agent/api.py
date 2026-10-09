"""Agent 流式 HTTP 适配。

用途：校验可信请求、映射 HTTP 错误并编码 SSE。
边界：不决定模型兜底或事务时序；由应用服务执行整轮用例。
"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, assert_never
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints

from odmflow.conversations import ConversationNotFound, DuplicateTurn, TurnConflict
from odmflow.conversations.presentation import message_projection, operation_projection
from odmflow.identity.dependencies import get_authorized_write_principal
from odmflow.identity.domain import AuthenticatedPrincipal

from .contracts import (
    AcceptedTurnEvent,
    CompletedTurnEvent,
    OperationTurnEvent,
    TokenTurnEvent,
    TurnStorageErrorEvent,
    TurnStreamEvent,
)
from .turn_service import AgentTurnService

router = APIRouter(prefix="/agent", tags=["agent"])


class TurnRequest(BaseModel):
    """只接受用户文本、可选对话和客户端幂等 ID。"""

    model_config = ConfigDict(extra="forbid")
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    conversation_id: UUID | None = None
    client_turn_id: UUID


def _service(request: Request) -> AgentTurnService:
    """从组合根取用例，保持存储／模型缺项的现行 503 语义。"""
    if request.app.state.conversation_service is None:
        raise HTTPException(status_code=503, detail="Conversation storage unavailable")
    if request.app.state.agent_service is None:
        raise HTTPException(status_code=503, detail="Agent model not configured")
    service: AgentTurnService = request.app.state.agent_turn_service
    return service


def _event(name: str, data: object) -> str:
    """把公开事件编码为单个 SSE 帧，不暴露内部历史。"""
    return f"event: {name}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


def _encode_event(event: TurnStreamEvent, include_details: bool = False) -> str:
    """显式映射应用事件到现有前端协议。"""
    if isinstance(event, AcceptedTurnEvent):
        return _event(
            "accepted",
            {
                "conversation_id": event.started.conversation_id,
                "turn_id": event.started.turn_id,
                "details_available": include_details,
                "user_message": message_projection(
                    event.started.user_message, include_details=include_details
                ),
            },
        )
    if isinstance(event, TokenTurnEvent):
        return _event("token", {"text": event.text})
    if isinstance(event, OperationTurnEvent):
        return _event(
            event.name,
            {"operation": operation_projection(event.operation, include_details=include_details)},
        )
    if isinstance(event, CompletedTurnEvent):
        return _event(
            "completed",
            {
                "assistant_message": message_projection(
                    event.assistant_message, include_details=include_details
                ),
                "outcome": event.outcome,
            },
        )
    if isinstance(event, TurnStorageErrorEvent):
        return _event("error", {"code": event.code})
    assert_never(event)


@router.post("/turns/stream")
async def stream_turn(
    payload: TurnRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authorized_write_principal)],
) -> StreamingResponse:
    """验证请求并在开始事务成功后开启流。

    Args:
        payload: 消息、可选对话与请求标识。
        request: 当前 HTTP 连接。
        principal: 服务端身份依赖验证后的主体。
    Returns:
        不缓存的 SSE 流，最终完成仅表示已成功保存。
    Raises:
        HTTPException: 归属 404、重复／占用 409、未配置 503。
    """
    service = _service(request)
    try:
        started = await service.start_turn(
            principal.user_id,
            str(payload.conversation_id) if payload.conversation_id else None,
            str(payload.client_turn_id),
            payload.message,
        )
    except ConversationNotFound as error:
        raise HTTPException(status_code=404, detail="Conversation not found") from error
    except (DuplicateTurn, TurnConflict) as error:
        raise HTTPException(status_code=409, detail="Turn conflict") from error

    async def generate() -> AsyncIterator[str]:
        """消费应用事件，HTTP 层只负责传输和编码。"""
        async for event in service.stream_turn(started, payload.message, request.is_disconnected):
            yield _encode_event(event, request.app.state.trace_debug_enabled)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
    )
