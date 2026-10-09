"""用途：校验有限计划、选择就绪任务与生成调用键。边界：纯策略，无框架/IO。"""

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

from odmflow.conversations.operation_records import JsonValue

from .configuration import TaskSettings
from .contracts import AgentTask, Capability, PlanDraft, TaskIntent, TaskStatus

_INTENT_CAPABILITIES = {
    TaskIntent.GENERAL_CHAT: frozenset(),
    TaskIntent.NEEDS_CLARIFICATION: frozenset(),
    TaskIntent.UNSUPPORTED_ACTION: frozenset(),
    TaskIntent.KNOWLEDGE_QA: frozenset({Capability.RAG_SEARCH}),
    TaskIntent.REQUIREMENT_ASSESSMENT: frozenset({Capability.ASSESS_ODM_REQUIREMENTS}),
    TaskIntent.OWN_ORDER_LOOKUP: frozenset({Capability.LIST_MY_ORDERS, Capability.GET_MY_ORDER}),
    TaskIntent.OWN_AFTER_SALES_LOOKUP: frozenset(
        {Capability.LIST_MY_AFTER_SALES, Capability.GET_MY_AFTER_SALES}
    ),
    TaskIntent.ORDER_APPLICATION: frozenset({Capability.PREPARE_ORDER_APPLICATION}),
    TaskIntent.AFTER_SALES_APPLICATION: frozenset({Capability.PREPARE_AFTER_SALES_APPLICATION}),
}
WRITE_PREVIEWS = frozenset(
    {Capability.PREPARE_ORDER_APPLICATION, Capability.PREPARE_AFTER_SALES_APPLICATION}
)
_IDENTITY_KEYS = frozenset({"user_id", "owner_id", "session_id", "session_token"})


def has_identity_argument(value: JsonValue) -> bool:
    """递归检查不允许的身份参数。Args: value: 外部JSON。Returns: 是否试图填入身份。"""
    if isinstance(value, dict):
        return bool(_IDENTITY_KEYS.intersection(value)) or any(
            has_identity_argument(item) for item in value.values()
        )
    return isinstance(value, list) and any(has_identity_argument(item) for item in value)


def validate_plan(
    draft: PlanDraft, allowed: frozenset[Capability], settings: TaskSettings
) -> tuple[AgentTask, ...]:
    """校验并转换草案。Args: draft: 模型草案；allowed: 当前许可；settings: 预算。

    Returns: 服务器ID及依赖的任务快照。Raises: ValueError: 非法计划。
    """
    if len(draft.tasks) > settings.max_tasks:
        raise ValueError("task_budget_exceeded")
    if sum(task.capability in WRITE_PREVIEWS for task in draft.tasks) > 1:
        raise ValueError("one_write_preview_per_turn")
    ids = {task.key: uuid4().hex for task in draft.tasks}
    if len(ids) != len(draft.tasks):
        raise ValueError("duplicate_task_key")
    if sum(task.capability == Capability.RAG_SEARCH for task in draft.tasks) > 1:
        raise ValueError("knowledge_tasks_must_be_combined")
    dependencies = {task.key: task.depends_on for task in draft.tasks}
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting or key not in dependencies:
            raise ValueError("invalid_task_dependencies")
        if key in visited:
            return
        visiting.add(key)
        for dependency in dependencies[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    result = []
    for task in draft.tasks:
        visit(task.key)
        choices = _INTENT_CAPABILITIES[task.intent]
        if has_identity_argument(task.arguments):
            raise ValueError("identity_argument_prohibited")
        if task.capability is None:
            if choices or task.arguments:
                raise ValueError("missing_or_unexpected_capability")
        elif task.capability not in allowed or task.capability not in choices:
            raise ValueError("capability_not_allowed")
        result.append(
            AgentTask(
                ids[task.key],
                task.intent,
                task.capability,
                json.dumps(task.arguments, ensure_ascii=False, allow_nan=False),
                tuple(ids[key] for key in task.depends_on),
                plan_key=task.key,
            )
        )
    return tuple(result)


def mark_blocked(tasks: tuple[AgentTask, ...]) -> tuple[AgentTask, ...]:
    """终结失败依赖项。Args: tasks: 当前快照。Returns: 连锁阻塞后的新快照。"""
    result = tasks
    while True:
        blocked = {
            task.task_id
            for task in result
            if task.status
            in {
                TaskStatus.FAILED,
                TaskStatus.NEEDS_INPUT,
                TaskStatus.BLOCKED,
                TaskStatus.WAITING_CONFIRMATION,
            }
        }
        updated = tuple(
            replace(task, status=TaskStatus.BLOCKED, error_code="dependency_unavailable")
            if task.status == TaskStatus.PENDING and blocked.intersection(task.depends_on)
            else task
            for task in result
        )
        if updated == result:
            return result
        result = updated


def merge_tasks(
    previous: tuple[AgentTask, ...], proposed: tuple[AgentTask, ...], settings: TaskSettings
) -> tuple[AgentTask, ...]:
    """有界追加任务，不能重写已规划的目标、状态或服务器ID。

    Args:
        previous: 本轮已有可信任务及状态。
        proposed: 通过单次计划校验的新草案。
        settings: 本轮不变的硬上限。
    Returns:
        旧任务原样保留、依赖重新绑定后的追加集合。
    Raises:
        ValueError: 旧目标被改写、任务/RAG数量超限。
    """
    old = {task.plan_key: task for task in previous}
    replacements = {
        task.task_id: old[task.plan_key].task_id for task in proposed if task.plan_key in old
    }
    additions = []
    for task in proposed:
        dependencies = tuple(replacements.get(dep, dep) for dep in task.depends_on)
        if task.plan_key in old:
            original = old[task.plan_key]
            if (
                task.intent != original.intent
                or task.capability != original.capability
                or task.arguments != original.arguments
                or dependencies != original.depends_on
            ):
                raise ValueError("existing_task_changed")
        else:
            additions.append(replace(task, depends_on=dependencies))
    tasks = previous + tuple(additions)
    if sum(task.capability in WRITE_PREVIEWS for task in tasks) > 1:
        raise ValueError("one_write_preview_per_turn")
    if len(tasks) > settings.max_tasks:
        raise ValueError("task_budget_exceeded")
    if sum(task.capability == Capability.RAG_SEARCH for task in tasks) > 1:
        raise ValueError("knowledge_tasks_must_be_combined")
    return tasks


def select_ready_task(tasks: tuple[AgentTask, ...]) -> AgentTask | None:
    """稳定选择一个可执行任务。Args: tasks: 有界快照。Returns: 就绪任务或None。"""
    completed = {task.task_id for task in tasks if task.status == TaskStatus.COMPLETED}
    return next(
        (
            task
            for task in tasks
            if task.status == TaskStatus.PENDING and set(task.depends_on) <= completed
        ),
        None,
    )


def call_key(capability: Capability, arguments: dict[str, JsonValue]) -> str:
    """生成规范化调用键。Args: capability: 能力；arguments: 已校验参数。

    Returns: 含能力名的摘要，不改变订单号大小写语义。
    """
    normalized = {
        key: value.strip() if isinstance(value, str) else value for key, value in arguments.items()
    }
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return f"{capability.value}:{hashlib.sha256(encoded.encode()).hexdigest()}"
