"""用途：保存任务公开快照与异常终态。边界：不调模型、不执行能力、不保存助手消息。"""

import json
from dataclasses import replace

from ..contracts import AgentStreamEvent
from ..run_context import AgentRunContext
from ..tasks.contracts import AgentTask, TaskStatus
from ..tasks.policy import mark_blocked
from .operations import (
    OperationDescriptor,
    OperationKind,
    OperationName,
    OperationStatus,
    WorkflowDetails,
)


def task_snapshot(tasks: tuple[AgentTask, ...]) -> str:
    """生成公开字段白名单。

    Args:
        tasks: 程序维护的任务，不接受模型自报状态。
    Returns:
        不含参数、身份、规划原文的JSON任务列表。
    """
    return json.dumps(
        [
            {
                "task_id": task.task_id,
                "intent": task.intent.value,
                "capability": task.capability.value if task.capability else None,
                "status": task.status.value,
                "error_code": task.error_code,
            }
            for task in tasks
        ],
        ensure_ascii=False,
    )


async def finalize_task_snapshot(
    context: AgentRunContext, reason: str
) -> tuple[AgentStreamEvent, ...]:
    """正常图结束或异常退出时只保存一次任务终态。

    Args:
        context: 本轮可信任务与操作存储。
        reason: 服务器确定的停止原因。
    Returns:
        已保存的开始/完成事件；尚未规划或已收口时为空。
    Raises:
        ConversationStorageUnavailable: 存储失败，不能冒充已保存。
    """
    if context.workflow_finalized or not context.tasks:
        return ()
    tasks = mark_blocked(context.tasks)
    if reason in {"deadline", "disconnected", "no_progress", "invalid_plan"}:
        tasks = tuple(
            replace(task, status=TaskStatus.FAILED, error_code=reason)
            if task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}
            else task
            for task in tasks
        )
    context.tasks = tasks
    details = WorkflowDetails(task_snapshot(tasks), reason)
    operation = await context.operations.start(
        OperationDescriptor(OperationKind.WORKFLOW, OperationName.FINALIZE_TASKS), details
    )
    finished = await context.operations.finish(operation.id, OperationStatus.COMPLETED, details)
    context.workflow_finalized = True
    return (
        AgentStreamEvent("operation_started", operation=operation),
        AgentStreamEvent("operation_finished", operation=finished),
    )
