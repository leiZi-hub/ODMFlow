"""用途：将真实操作详情封装为兼容schema1的存储JSON。边界：不运行工具、不写SQL，不改变实际RAG证据。"""

import json

from odmflow.conversations.operation_records import JsonValue

from .operations import (
    OperationDescriptor,
    OperationDetails,
    OperationKind,
    OperationName,
    OperationStatus,
    RagDetails,
    SummaryDetails,
    ToolDetails,
    WorkflowDetails,
)
from .rag_trace import KnowledgeTraceTooLarge, project_rag_trace


def operation_payload(
    descriptor: OperationDescriptor, details: OperationDetails, status: OperationStatus
) -> str:
    """序列化版本化操作描述与有类型明细，不包含当前身份或秘密配置。

    Args:
        descriptor: 后端固定枚举对象。
        details: RAG或工具的真实执行信息。
        status: 实际生命周期。
    Returns:
        可写入操作快照的JSON文本。
    Raises:
        ValueError: 工具快照超过允许大小。
    """
    payload: dict[str, JsonValue] = {
        "schema_version": 1,
        "descriptor": {"kind": descriptor.kind.value, "name": descriptor.name.value},
        "sources": [],
    }
    if isinstance(details, WorkflowDetails):
        if len(details.tasks_json.encode()) > 8192:
            raise ValueError("任务快照超过8KiB")
        payload["tasks"] = json.loads(details.tasks_json)
        payload["stop_reason"] = details.stop_reason
        payload["summary"] = (
            ("正在识别任务" if status == OperationStatus.RUNNING else "任务识别完成")
            if descriptor.name == OperationName.PLAN_TASKS
            else ("正在整理任务结果" if status == OperationStatus.RUNNING else "本轮任务结果")
        )
        payload["details"] = {"error_code": details.error_code}
    elif isinstance(details, RagDetails):
        if details.task_id:
            payload["task_id"] = details.task_id
        payload["summary"] = (
            "正在检索知识库" if status == OperationStatus.RUNNING else "知识库检索结束"
        )
        payload["details"] = {"query": details.query, "error_code": details.error_code}
        if details.prepared is not None:
            prepared = details.prepared
            payload["details"] = json.loads(project_rag_trace(prepared))
            payload["sources"] = [
                {
                    "source_id": source.source_id,
                    "chunk_id": source.chunk_id,
                    "title": source.title,
                    "section_path": source.section_path,
                    "version": source.version,
                }
                for source in prepared.sources
            ]
            payload["summary"] = (
                f"检索{len(prepared.candidates)}个候选，注入{len(prepared.sources)}个片段"
            )
        if details.original_query is not None:
            rag_payload = payload["details"]
            assert isinstance(rag_payload, dict)
            rag_payload["query_compaction"] = {
                "original_query": details.original_query,
                "effective_query": details.query,
                "attempts": 1,
                "elapsed_ms": details.compaction_elapsed_ms,
            }
    else:
        if isinstance(details, SummaryDetails):
            arguments = (
                {"pending_messages": details.pending_messages, "has_more": details.has_more}
                if status == OperationStatus.RUNNING
                else {}
            )
            result = (
                None
                if status == OperationStatus.RUNNING
                else {
                    "batches": details.batches,
                    "recent_messages": details.recent_messages,
                    "degraded": details.degraded,
                    "summary": details.summary,
                }
            )
            details = ToolDetails(
                json.dumps(arguments),
                json.dumps(result, ensure_ascii=False) if result is not None else None,
                error_code=details.error_code,
            )
        if any(
            len(value.encode()) > 8192
            for value in (
                details.arguments_json,
                details.result_json or "",
            )
        ):
            raise ValueError("工具参数或结果超过8KiB")
        if descriptor.kind == OperationKind.CONTEXT:
            payload["summary"] = (
                ("正在准备用户画像" if status == OperationStatus.RUNNING else "用户画像准备结束")
                if descriptor.name == OperationName.PREPARE_PROFILE
                else (
                    "正在整理较早对话" if status == OperationStatus.RUNNING else "较早对话整理结束"
                )
            )
        else:
            label = {
                OperationName.ASSESS_ODM_REQUIREMENTS: "需求评估",
                OperationName.LIST_MY_ORDERS: "本人订单列表",
                OperationName.GET_MY_ORDER: "本人订单详情",
                OperationName.LIST_MY_AFTER_SALES: "本人售后列表",
                OperationName.GET_MY_AFTER_SALES: "本人售后详情",
                OperationName.PREPARE_ORDER_APPLICATION: "模拟订单确认卡准备",
                OperationName.PREPARE_AFTER_SALES_APPLICATION: "模拟售后确认卡准备",
            }[descriptor.name]
            payload["summary"] = (
                "正在查询" + label if status == OperationStatus.RUNNING else label + "结束"
            )
        if descriptor.kind == OperationKind.TOOL:
            payload["task_id"] = details.task_id
            payload["attempt"] = details.attempt
        payload["details"] = {
            "arguments": json.loads(details.arguments_json),
            "result": json.loads(details.result_json) if details.result_json else None,
            "tool_call_id": details.tool_call_id,
            "error_code": details.error_code,
        }
    if details.error_code:
        payload["error_code"] = details.error_code
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if isinstance(details, RagDetails) and len(encoded.encode("utf-8")) > 128 * 1024:
        raise KnowledgeTraceTooLarge("完整知识快照超过128KiB，请降低上下文预算")
    return encoded
