"""用途：为消息历史与SSE输出统一安全投影。边界：不查询SQL、不决定owner，不依赖Agent或框架。"""

from dataclasses import asdict

from .domain import MessageView
from .operation_records import JsonValue, OperationRecord


def operation_projection(record: OperationRecord, include_details: bool) -> dict[str, JsonValue]:
    """为SSE和历史生成同一公开结构，在服务端删除未经授权的详细内容。

    Args:
        record: 已保存的快照。
        include_details: 服务端全局调试开关；调用前必须验证本人归属，不是前端参数。
    Returns:
        有实际状态与ID的安全JSON字段。
    """
    payload = record.payload()
    projected: dict[str, JsonValue] = {
        key: payload[key]
        for key in (
            "schema_version",
            "descriptor",
            "summary",
            "sources",
            "error_code",
            "tasks",
            "stop_reason",
            "task_id",
            "attempt",
        )
        if key in payload
    }
    if include_details and "details" in payload:
        projected["details"] = payload["details"]
    projected.update(
        operation_id=record.id,
        turn_id=record.turn_id,
        sequence=record.sequence,
        status=record.status,
        started_at=record.started_at.isoformat(),
        finished_at=record.finished_at.isoformat() if record.finished_at else None,
        elapsed_ms=record.elapsed_ms,
    )
    return projected


def message_projection(message: MessageView, include_details: bool) -> dict[str, object]:
    """输出消息和安全操作投影，不暴露内部payload_json。

    Args:
        message: 当前账号可见消息。
        include_details: 服务端调试开关，不改变登录和对话归属要求。
    Returns:
        HTTP/SSE共用的消息结构。
    """
    result: dict[str, object] = asdict(message)
    result["operations"] = [
        operation_projection(row, include_details) for row in message.operations
    ]
    result["details_available"] = include_details
    return result
