"""用途：逐次检查系统、schema、历史和实际结果预算。边界：只删完整旧对话组，不截断当前问题或证据。"""

import json

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from odmflow.conversations.operation_records import JsonValue

from ..contracts import ContextBudgetExceeded
from ..run_context import AgentRunContext
from .configuration import ContextSettings
from .preparation import text_units


def prepare_model_input(
    messages: list[BaseMessage],
    tool_schemas: list[dict[str, JsonValue]],
    settings: ContextSettings,
    context: AgentRunContext,
) -> list[BaseMessage]:
    """返回预算内完整消息副本；必须保留项仍超限时拒绝请求。

    Args:
        messages: 含系统、当前需求及真实配对结果的消息。
        tool_schemas: 本次实际绑定的工具schema，同样计入预算。
        settings: 模型窗口、输出保留和安全余量。
        context: 记录旧消息裁剪提示，不修改历史库。
    Returns:
        预算内消息副本，仅移除完整旧对话组。
    Raises:
        ContextBudgetExceeded: 关键消息仍超限，禁止静默截断证据。"""
    bounded = list(messages)
    schema_units = text_units(json.dumps(tool_schemas, ensure_ascii=False, default=str))
    while (
        512
        + schema_units
        + sum(
            text_units(json.dumps(message.model_dump(), ensure_ascii=False, default=str)) + 32
            for message in bounded
        )
        > settings.input_budget
    ):
        starts = [i for i, message in enumerate(bounded) if isinstance(message, HumanMessage)]
        if len(starts) <= 1:
            raise ContextBudgetExceeded
        bounded = [
            message for message in bounded[: starts[1]] if isinstance(message, SystemMessage)
        ] + bounded[starts[1] :]
    if len(bounded) < len(messages) and not context.budget_notice:
        context.budget_notice = "本轮上下文较长，部分较早内容未纳入本次回答。\n\n"
    return bounded
