"""用途：构建唯一显式任务StateGraph。边界：无自由ReAct循环、持久checkpoint或业务SQL。"""

from collections.abc import Mapping
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ..memory.configuration import ContextSettings
from ..run_context import AgentRunContext
from ..tasks.configuration import TaskSettings
from ..tasks.contracts import Capability
from ..tools.contracts import CapabilityDefinition
from .task_nodes import TaskGraphState, TaskNodes


def build_agent_graph(
    model: BaseChatModel,
    catalog: Mapping[Capability, CapabilityDefinition],
    context_settings: ContextSettings,
    task_settings: TaskSettings,
) -> CompiledStateGraph[Any, AgentRunContext, Any, Any]:
    """编译固定串行节点和条件边；模型不能直接控制路由。

    Args:
        model: 已配置的Chat适配，不在此连接数据库。
        catalog: 服务器显式允许的能力定义。
        context_settings: 每次模型输入与输出预算。
        task_settings: 全轮任务、调用及修正硬上限。
    Returns:
        可异步流式运行的图；每轮可信状态经Runtime注入。
    """
    nodes = TaskNodes(model, catalog, context_settings, task_settings)
    builder = StateGraph(TaskGraphState, context_schema=AgentRunContext)
    for name in (
        "plan_tasks",
        "validate_plan",
        "select_ready_task",
        "execute_allowed_capability",
        "record_result",
        "check_progress",
        "replan_tasks",
        "compose_reply",
        "finalize_tasks",
    ):
        builder.add_node(name, getattr(nodes, name))
    builder.add_edge(START, "plan_tasks")
    builder.add_edge("plan_tasks", "validate_plan")
    builder.add_edge("replan_tasks", "validate_plan")
    builder.add_edge("validate_plan", "select_ready_task")
    builder.add_conditional_edges(
        "select_ready_task", nodes.route_selected, ["execute_allowed_capability", "compose_reply"]
    )
    builder.add_edge("execute_allowed_capability", "record_result")
    builder.add_edge("record_result", "check_progress")
    builder.add_conditional_edges(
        "check_progress",
        nodes.route_progress,
        ["select_ready_task", "replan_tasks", "compose_reply"],
    )
    builder.add_edge("compose_reply", "finalize_tasks")
    builder.add_edge("finalize_tasks", END)
    return builder.compile()
