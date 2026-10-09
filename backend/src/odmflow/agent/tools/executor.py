"""用途：统一参数门禁、额度与真实能力记录。边界：不定义业务表或自由ReAct循环。"""

import asyncio
import json
from collections.abc import Mapping
from dataclasses import replace
from time import perf_counter

from odmflow.conversations import ConversationStorageUnavailable
from odmflow.knowledge.domain import KnowledgeError

from ..contracts import AgentStreamEvent, QueryCompactionFailed
from ..run_context import AgentRunContext
from ..tasks.budget import TaskLimitExceeded
from ..tasks.contracts import AgentTask, Capability, TaskResult
from ..tasks.policy import call_key
from ..tracing.operations import (
    OperationDescriptor,
    OperationKind,
    OperationName,
    OperationStatus,
    ToolDetails,
)
from .availability import capability_available
from .contracts import CapabilityDefinition, CapabilityRisk
from .read_retry import ReadRetryPolicy
from .validation import InvalidCapabilityArguments, mentions_exact_order_number, validate_arguments


class CapabilityExecutor:
    """只执行显式目录且先存开始记录；状态和预算属于本轮context。"""

    def __init__(self, catalog: Mapping[Capability, CapabilityDefinition]) -> None:
        """保存不可由模型替换的能力定义。"""
        self.catalog = catalog

    async def execute(self, task: AgentTask, context: AgentRunContext) -> TaskResult:
        """检查参数/额度后执行一次；仅本人订单的分类故障可追加一次。

        Args:
            task: 服务器认可的单个任务。
            context: 本轮身份绑定端口、预算和记录出口。
        Returns:
            实际结果或受控拒绝；不接受模型自报成功。
        Raises:
            ConversationStorageUnavailable: 记录未保存，不继续调用。
            asyncio.CancelledError: 中断终态保存后继续传播取消。"""
        definition = self.catalog.get(task.capability) if task.capability else None
        if definition is None:
            return TaskResult(task.task_id, "unavailable", error_code="capability_unavailable")
        if not capability_available(definition.name, context):
            return TaskResult(task.task_id, "unavailable", error_code="orders_unavailable")
        try:
            payload = validate_arguments(task, definition.input_schema)
        except InvalidCapabilityArguments as error:
            if not context.repair_arguments or not all(issue.repairable for issue in error.issues):
                return TaskResult(task.task_id, "invalid_arguments", error_code="invalid_arguments")
            try:
                context.budget.consume_repair()
                repaired = await context.repair_arguments(
                    task, error.issues, context.argument_evidence
                )
                task = replace(task, arguments_json=json.dumps(repaired, ensure_ascii=False))
                payload = validate_arguments(task, definition.input_schema)
            except InvalidCapabilityArguments, TaskLimitExceeded, ValueError:
                return TaskResult(
                    task.task_id, "needs_input", error_code="arguments_need_clarification"
                )
        task = replace(task, arguments_json=payload.model_dump_json(exclude_none=True))
        if task.capability == Capability.GET_MY_ORDER:
            number = task.arguments.get("order_no")
            evidence = context.argument_evidence
            if not isinstance(number, str) or (
                number not in evidence.known_order_nos
                and not mentions_exact_order_number(number, evidence.user_messages)
            ):
                return TaskResult(
                    task.task_id, "needs_input", error_code="order_target_not_grounded"
                )
        if task.capability == Capability.RAG_SEARCH and context.knowledge_called:
            return TaskResult(task.task_id, "unavailable", error_code="rag_limit_reached")
        key = call_key(definition.name, task.arguments)
        try:
            context.budget.consume_capability(key)
        except TaskLimitExceeded:
            return TaskResult(
                task.task_id,
                "unavailable",
                error_code="duplicate_capability_call"
                if key in context.budget.called_keys
                else "capability_budget_exceeded",
            )
        result = await self._attempt(task, context, definition, 1)
        if definition.risk == CapabilityRisk.PRIVATE_READONLY and ReadRetryPolicy().should_retry(
            result, 1, context.budget, context.deadline - perf_counter()
        ):
            context.budget.consume_readonly_retry()
            await asyncio.sleep(0.1)
            context.budget.consume_capability(key, retry=True)
            result = await self._attempt(task, context, definition, 2)
        return result

    async def _attempt(
        self,
        task: AgentTask,
        context: AgentRunContext,
        definition: CapabilityDefinition,
        attempt: int,
    ) -> TaskResult:
        """保存一次实际执行；存储失败不吞掉，取消先记录中断。"""
        writer = context.emit or (lambda event: None)
        if definition.name == Capability.RAG_SEARCH:
            try:
                return await definition.execute(task, context)
            except QueryCompactionFailed as error:
                return TaskResult(task.task_id, "unavailable", error_code=error.code)
            except KnowledgeError:
                return TaskResult(task.task_id, "unavailable", error_code="knowledge_unavailable")
        descriptor = OperationDescriptor(OperationKind.TOOL, OperationName(definition.name.value))
        details = ToolDetails(task.arguments_json, task_id=task.task_id, attempt=attempt)
        started = await context.operations.start(descriptor, details)
        writer(AgentStreamEvent("operation_started", operation=started))
        try:
            result = await definition.execute(task, context)
        except asyncio.CancelledError:
            await context.operations.finish(
                started.id,
                OperationStatus.INTERRUPTED,
                replace(details, error_code="tool_interrupted"),
            )
            raise
        except ConversationStorageUnavailable:
            raise
        except Exception:
            result = TaskResult(task.task_id, "unavailable", error_code="tool_execution_failed")
        finished = await context.operations.finish(
            started.id,
            OperationStatus.COMPLETED
            if result.code in ("ok", "empty", "not_found", "awaiting_confirmation")
            else OperationStatus.FAILED,
            replace(
                details,
                result_json=json.dumps(result.data, ensure_ascii=False),
                error_code=result.error_code,
            ),
        )
        writer(AgentStreamEvent("operation_finished", operation=finished))
        return result
