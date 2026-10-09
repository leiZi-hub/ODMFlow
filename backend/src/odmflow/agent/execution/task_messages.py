"""用途：配对真实规划请求及执行结果。边界：不伪造独立业务工具的模型调用。"""

import json
from dataclasses import asdict

from langchain_core.messages import BaseMessage, ToolMessage

from ..tasks.contracts import TaskResult
from .task_planner import PlannedTasks


def build_result_messages(
    messages: list[BaseMessage], planned: PlannedTasks, results: tuple[TaskResult, ...]
) -> list[BaseMessage]:
    """关闭该次真实plan_tasks调用；仅加入程序产生的有限执行结果。

    Args:
        messages: 调用前的完整消息序列。
        planned: 主模型真实提出的规划调用。
        results: 该次规划实际执行的结果，不重复已配对的旧结果。
    Returns:
        原始AI调用与同一call_id的结果ToolMessage；不伪造业务工具调用。"""
    return [
        *messages,
        planned.request,
        ToolMessage(
            content=json.dumps(
                {"results": [asdict(result) for result in results]}, ensure_ascii=False
            ),
            name="plan_tasks",
            tool_call_id=planned.request.tool_calls[0]["id"],
        ),
    ]
