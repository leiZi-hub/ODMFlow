"""用途：显式任务图节点适配。边界：调度规则在tasks，业务执行在tools/orders，身份只在Runtime。"""

from collections.abc import Mapping
from dataclasses import replace
from typing import TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.runtime import Runtime

from odmflow.conversations import ConversationStorageUnavailable
from odmflow.knowledge.domain import KnowledgeError
from odmflow.orders.domain import OrderReadUnavailable

from ..contracts import AgentStreamEvent, QueryCompactionFailed
from ..memory.configuration import ContextSettings
from ..memory.model_budget import prepare_model_input
from ..replies import build_partial_reply
from ..run_context import AgentRunContext
from ..tasks.configuration import TaskSettings
from ..tasks.contracts import AgentTask, Capability, TaskIntent, TaskResult, TaskStatus
from ..tasks.policy import mark_blocked, merge_tasks, select_ready_task, validate_plan
from ..tools.availability import capability_available
from ..tools.contracts import CapabilityDefinition
from ..tools.executor import CapabilityExecutor
from ..tracing.operations import (
    OperationDescriptor,
    OperationKind,
    OperationName,
    OperationStatus,
    WorkflowDetails,
)
from ..tracing.task_workflow import finalize_task_snapshot, task_snapshot
from .prompts import AGENT_SYSTEM_PROMPT
from .task_messages import build_result_messages
from .task_planner import PlannedTasks, TaskPlanner


class TaskGraphState(TypedDict, total=False):
    """有界工作状态；不放服务、身份、连接和密钥。"""

    messages: list[BaseMessage]
    planned: PlannedTasks
    tasks: tuple[AgentTask, ...]
    results: tuple[TaskResult, ...]
    active_task_id: str | None
    result: TaskResult
    stop_reason: str
    final_reply: str
    plan_operation_id: str
    route: str
    result_cursor: int


class TaskNodes:
    """图节点仅协调现有服务；不保留跨轮状态。"""

    def __init__(
        self,
        model: BaseChatModel,
        catalog: Mapping[Capability, CapabilityDefinition],
        context_settings: ContextSettings,
        task_settings: TaskSettings,
    ) -> None:
        """构造规划与执行适配，不执行IO。"""
        self.model, self.catalog = model, catalog
        self.context_settings, self.task_settings = context_settings, task_settings
        self.planner = TaskPlanner(model, catalog, context_settings)
        self.executor = CapabilityExecutor(catalog)

    async def plan_tasks(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """先保存开始记录再调用结构化规划；不输出规划文本。

        Args:
            state: 已准备的模型消息，含当前完整问题。
            runtime: 当轮预算、可信端口和操作事件出口。
        Returns:
            草案、规划记录ID和空的初始任务/结果。
        Raises:
            Exception: 规划或保存失败，交外层用例安全收口。
        """
        context = runtime.context
        context.emit = runtime.stream_writer
        context.repair_arguments = lambda task, errors, evidence: self.planner.repair_arguments(
            task, errors, evidence, context
        )
        operation = await context.operations.start(
            OperationDescriptor(OperationKind.WORKFLOW, OperationName.PLAN_TASKS), WorkflowDetails()
        )
        runtime.stream_writer(AgentStreamEvent("operation_started", operation=operation))
        try:
            planned = await self.planner.plan(state["messages"], context)
        except BaseException:
            await context.operations.finish(
                operation.id, OperationStatus.FAILED, WorkflowDetails(error_code="planning_failed")
            )
            raise
        return {"planned": planned, "plan_operation_id": operation.id, "tasks": (), "results": ()}

    async def validate_plan(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """校验依赖、能力和数量；修正时保留已有ID、结果与额度。

        Args:
            state: 实际规划草案及已有任务。
            runtime: 当轮许可端口及操作存储。
        Returns:
            有效任务或invalid_plan停止原因；不把草案当权限。
        Raises:
            ConversationStorageUnavailable: 校验记录无法保存。
        """
        previous = state.get("tasks", ())
        allowed = frozenset(
            cap for cap in self.catalog if capability_available(cap, runtime.context)
        )
        try:
            proposed = validate_plan(state["planned"].draft, allowed, self.task_settings)
            tasks = merge_tasks(previous, proposed, self.task_settings)
            status, reason = OperationStatus.COMPLETED, None
        except ValueError:
            tasks, status, reason = previous, OperationStatus.FAILED, "invalid_plan"
        finished = await runtime.context.operations.finish(
            state["plan_operation_id"],
            status,
            WorkflowDetails(task_snapshot(tasks), reason, reason),
        )
        runtime.stream_writer(AgentStreamEvent("operation_finished", operation=finished))
        runtime.context.tasks = tasks
        return {"tasks": tasks, "stop_reason": reason or ""}

    def select_ready_task(self, state: TaskGraphState) -> TaskGraphState:
        """程序稳定选取一个就绪任务；没有任务则进入汇总。

        Args:
            state: 程序维护的任务与停止原因。
        Returns:
            连锁阻塞后的任务及就绪任务ID（无则None）。
        """
        tasks = mark_blocked(state["tasks"])
        selected = None if state.get("stop_reason") else select_ready_task(tasks)
        return {"tasks": tasks, "active_task_id": selected.task_id if selected else None}

    def route_selected(self, state: TaskGraphState) -> str:
        """返回固定下一节点，不读取模型路由文字。

        Args:
            state: 服务器选择的active_task_id。
        Returns:
            execute_allowed_capability或compose_reply节点名。
        """
        return "execute_allowed_capability" if state.get("active_task_id") else "compose_reply"

    async def execute_allowed_capability(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """执行一项可信目录能力；无工具意图仅产生程序状态。

        Args:
            state: 就绪任务ID及已验证任务集合。
            runtime: 可信目录执行所需的当轮上下文。
        Returns:
            实际TaskResult；不接受模型自报完成。
        Raises:
            ConversationStorageUnavailable: 执行记录无法保存。
        """
        task = next(task for task in state["tasks"] if task.task_id == state["active_task_id"])
        runtime.context.active_task_id = task.task_id
        runtime.context.tasks = tuple(
            replace(item, status=TaskStatus.RUNNING) if item.task_id == task.task_id else item
            for item in state["tasks"]
        )
        result = (
            await self.executor.execute(task, runtime.context)
            if task.capability
            else TaskResult(
                task.task_id,
                "needs_input" if task.intent == TaskIntent.NEEDS_CLARIFICATION else "ok",
                {"intent": task.intent.value},
            )
        )
        return {"result": result}

    def record_result(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """能力已提交后更新结果；供deadline保底读取，不读取外部图状态。

        Args:
            state: 实际执行结果与当前任务。
            runtime: 外层异常收口可访问的当轮上下文。
        Returns:
            更新后的任务终态与累计结果。
        """
        result = state["result"]
        status = (
            TaskStatus.WAITING_CONFIRMATION
            if result.code == "awaiting_confirmation"
            else TaskStatus.COMPLETED
            if result.code in ("ok", "empty", "not_found")
            else TaskStatus.NEEDS_INPUT
            if result.code in ("needs_input", "invalid_arguments")
            else TaskStatus.FAILED
        )
        tasks = tuple(
            replace(task, status=status, error_code=result.error_code)
            if task.task_id == result.task_id
            else task
            for task in state["tasks"]
        )
        results = (*state["results"], result)
        runtime.context.task_results = results
        runtime.context.tasks = tasks
        runtime.context.active_task_id = None
        return {"tasks": tasks, "results": results}

    def check_progress(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """就绪则继续；本人列表新事实允许一次有限修正，否则停止。

        Args:
            state: 已执行结果及剩余任务。
            runtime: 全轮共享预算，不因修正重置。
        Returns:
            固定下一节点及必要的安全停止原因。
        """
        tasks = mark_blocked(state["tasks"])
        if select_ready_task(tasks):
            return {"tasks": tasks, "route": "select_ready_task"}
        last = next(task for task in tasks if task.task_id == state["result"].task_id)
        budget = runtime.context.budget
        if (
            last.capability == Capability.LIST_MY_ORDERS
            and state["result"].code == "ok"
            and budget.replans < budget.settings.max_replans
            and len(tasks) < budget.settings.max_tasks
            and budget.model_calls < budget.settings.max_model_calls - 1
            and budget.capability_calls < budget.settings.max_capability_calls
        ):
            return {"tasks": tasks, "route": "replan_tasks"}
        errors = {result.error_code for result in state["results"]}
        reason = (
            "awaiting_confirmation"
            if any(task.status == TaskStatus.WAITING_CONFIRMATION for task in tasks)
            else "budget_exhausted"
            if errors & {"capability_budget_exceeded", "query_compaction_budget_exhausted"}
            else "no_progress"
            if errors & {"duplicate_capability_call", "rag_limit_reached"}
            else "needs_input"
            if any(task.status == TaskStatus.NEEDS_INPUT for task in tasks)
            else "all_terminal"
        )
        return {"tasks": tasks, "route": "compose_reply", "stop_reason": reason}

    def route_progress(self, state: TaskGraphState) -> str:
        """使用服务器计算的固定路由。

        Args:
            state: check_progress输出的route。
        Returns:
            条件边许可的固定节点名。
        """
        return state["route"]

    async def replan_tasks(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """关闭上次规划配对，保留已有任务，再基于真实结果补一轮草案。

        Args:
            state: 旧规划、任务和真实执行结果。
            runtime: 全轮唯一修正额度及操作记录。
        Returns:
            新草案与配对消息；旧任务仍交validate_plan合并。
        Raises:
            Exception: 模型或记录失败，不退回自由循环。
        """
        messages = build_result_messages(
            state["messages"], state["planned"], state["results"][state.get("result_cursor", 0) :]
        )
        operation = await runtime.context.operations.start(
            OperationDescriptor(OperationKind.WORKFLOW, OperationName.PLAN_TASKS),
            WorkflowDetails(task_snapshot(state["tasks"])),
        )
        runtime.stream_writer(AgentStreamEvent("operation_started", operation=operation))
        try:
            planned = await self.planner.replan(
                state["tasks"],
                state["results"],
                [
                    *messages,
                    SystemMessage(
                        "基于刚取得的本人结果，仅追加原目标所需的新任务；旧key保留，不重复查询。多笔不猜选，资料不足先澄清。"
                    ),
                ],
                runtime.context,
            )
        except BaseException:
            await runtime.context.operations.finish(
                operation.id,
                OperationStatus.FAILED,
                WorkflowDetails(error_code="replanning_failed"),
            )
            raise
        return {
            "messages": messages,
            "planned": planned,
            "plan_operation_id": operation.id,
            "stop_reason": "",
            "result_cursor": len(state["results"]),
        }

    async def compose_reply(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """唯一正文节点；保留原始问题及实际结果，不声明未执行写动作。

        Args:
            state: 最终任务、实际结果及完整问题。
            runtime: 预留模型额度、输入预算与事件出口。
        Returns:
            最终正文/真实部分结果保底及停止原因。
        Raises:
            Exception: 没有可核实结果或无法安全生成保底时向外收口。
        """
        context = runtime.context
        if state.get("stop_reason") == "invalid_plan":
            raise ValueError("invalid_plan")
        if state["results"] and all(result.code == "unavailable" for result in state["results"]):
            code = next(
                (
                    result.error_code
                    for result in state["results"]
                    if result.error_code and result.error_code.startswith("query_compaction_")
                ),
                None,
            )
            if code:
                raise QueryCompactionFailed(code)
            if all(
                task.capability in {Capability.LIST_MY_ORDERS, Capability.GET_MY_ORDER}
                for task in state["tasks"]
                if any(result.task_id == task.task_id for result in state["results"])
            ):
                raise OrderReadUnavailable(False)
            raise KnowledgeError("没有可核实的执行结果，不继续生成企业事实")
        messages = build_result_messages(
            state["messages"], state["planned"], state["results"][state.get("result_cursor", 0) :]
        )
        messages = [
            SystemMessage(
                AGENT_SYSTEM_PROMPT
                + "能力已由程序执行完毕。只根据真实results答原问题；无资料不编造，查空不是成功。"
                "订单仅为模拟。不要暴露实现细节。"
                "awaiting_confirmation只表示已准备卡片、尚未提交；提示用户核对确认卡并点击确认，不能称已下单或已受理。"
            ),
            *messages,
        ]
        bounded = prepare_model_input(messages, [], self.context_settings, context)
        context.budget.consume_model(final=True)
        reason = state.get("stop_reason") or "all_terminal"
        try:
            response = await self.model.ainvoke(
                bounded, stream=True, max_tokens=self.context_settings.output_tokens
            )
            reply = str(response.text).strip()
            if not reply:
                raise ValueError("empty_final_reply")
        except ConversationStorageUnavailable:
            raise
        except Exception:
            reason = "no_progress"
            reply = build_partial_reply(state["results"], "no_progress")
            if not reply:
                raise
            runtime.stream_writer(AgentStreamEvent("token", text=reply))
        return {"final_reply": reply, "stop_reason": reason}

    async def finalize_tasks(
        self, state: TaskGraphState, runtime: Runtime[AgentRunContext]
    ) -> TaskGraphState:
        """保存任务终态后发事件；不代替外层助手消息原子保存。

        Args:
            state: 程序维护的最终任务及停止原因。
            runtime: 当轮绑定的操作存储。
        Returns:
            空图更新；已保存的事件经stream_writer发出。
        Raises:
            ConversationStorageUnavailable: 不得将未保存记录宣称完成。
        """
        runtime.context.tasks = state["tasks"]
        for event in await finalize_task_snapshot(runtime.context, state["stop_reason"]):
            runtime.stream_writer(event)
        return {}
