"""用途：承载一轮运行的可信端口、知识证据与检索预算。

边界：由应用层逐轮创建，不进入模型参数，不执行 HTTP、SQL 或框架图。
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from odmflow.conversations.context_contracts import ContextRequest
from odmflow.conversations.operation_records import JsonValue

from .contracts import AgentStreamEvent
from .tasks.budget import TaskBudget
from .tasks.configuration import TaskSettings
from .tasks.contracts import AgentTask, ArgumentEvidence, ArgumentIssue, TaskResult
from .tools.rag.evidence import PreparedKnowledge

if TYPE_CHECKING:
    from .ports import (
        AgentAfterSalesPort,
        AgentApplicationPort,
        AgentContextPort,
        AgentKnowledgePort,
        AgentOperationRecorder,
        AgentOrderReadPort,
        AgentProfilePort,
    )


@dataclass
class AgentRunContext:
    """请求级运行上下文；不能保存在全局 runner 或作为用户画像复用。"""

    operations: AgentOperationRecorder
    knowledge: AgentKnowledgePort | None = None
    rag_evidence: PreparedKnowledge | None = None
    knowledge_called: bool = False
    knowledge_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    compact_query: Callable[[str], Awaitable[str]] | None = None
    context_store: AgentContextPort | None = None
    context_request: ContextRequest | None = None
    budget_notice: str = ""
    profile_store: AgentProfilePort | None = None
    profile_values: tuple[tuple[str, str], ...] = ()
    budget: TaskBudget = field(default_factory=lambda: TaskBudget(TaskSettings()))
    task_results: tuple[TaskResult, ...] = ()
    tasks: tuple[AgentTask, ...] = ()
    workflow_finalized: bool = False
    active_task_id: str | None = None
    argument_evidence: ArgumentEvidence = field(default_factory=lambda: ArgumentEvidence(()))
    repair_arguments: (
        Callable[
            [AgentTask, tuple[ArgumentIssue, ...], ArgumentEvidence],
            Awaitable[dict[str, JsonValue]],
        ]
        | None
    ) = None
    emit: Callable[[AgentStreamEvent], None] | None = None
    deadline: float = float("inf")
    orders: AgentOrderReadPort | None = None
    actions: AgentApplicationPort | None = None
    after_sales: AgentAfterSalesPort | None = None
    application_prepared: bool = False
