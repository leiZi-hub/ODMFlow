"""用途：定义可信调用点使用的操作枚举和明细。

边界：不执行工具、SQL或HTTP，不通过模型文字推断操作是否发生。
"""

from dataclasses import dataclass
from enum import StrEnum

from odmflow.conversations.operation_records import OperationRecord

from ..tools.rag.evidence import PreparedKnowledge


class OperationKind(StrEnum):
    """真实操作类别，不是意图分类。"""

    RAG = "rag"
    TOOL = "tool"
    CONTEXT = "context"
    WORKFLOW = "workflow"


class OperationName(StrEnum):
    """当前有实现的操作名；新增工具时在可信注册点赋值。"""

    RAG_SEARCH = "rag_search"
    ASSESS_ODM_REQUIREMENTS = "assess_odm_requirements"
    SUMMARIZE_CONTEXT = "summarize_context"
    PREPARE_PROFILE = "prepare_profile"
    PLAN_TASKS = "plan_tasks"
    FINALIZE_TASKS = "finalize_tasks"
    LIST_MY_ORDERS = "list_my_orders"
    GET_MY_ORDER = "get_my_order"
    LIST_MY_AFTER_SALES = "list_my_after_sales"
    GET_MY_AFTER_SALES = "get_my_after_sales"
    PREPARE_ORDER_APPLICATION = "prepare_order_application"
    PREPARE_AFTER_SALES_APPLICATION = "prepare_after_sales_application"


class OperationStatus(StrEnum):
    """操作生命周期；不等于整轮状态。"""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class OperationDescriptor:
    """枚举描述对象，可信调用点直接填写，不重复内部字符串白名单。"""

    kind: OperationKind
    name: OperationName


@dataclass(frozen=True)
class RagDetails:
    """检索准备或结束快照，候选/选用/实际注入保持独立。"""

    query: str
    prepared: PreparedKnowledge | None = None
    error_code: str | None = None
    original_query: str | None = None
    compaction_elapsed_ms: float | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class ToolDetails:
    """经允许字段过滤的工具参数/结果JSON，失败不保存SDK原始异常。"""

    arguments_json: str
    result_json: str | None = None
    tool_call_id: str | None = None
    error_code: str | None = None
    task_id: str | None = None
    attempt: int = 1


@dataclass(frozen=True)
class SummaryDetails:
    """摘要整理的内部详情；公开JSON继续兼容schema1，不冒充业务工具。"""

    pending_messages: int | None = None
    has_more: bool = False
    batches: int = 0
    recent_messages: int = 0
    degraded: bool = False
    summary: str = ""
    error_code: str | None = None


@dataclass(frozen=True)
class WorkflowDetails:
    """程序任务状态，不含模型思维、完整参数、用户身份。"""

    tasks_json: str = "[]"
    stop_reason: str | None = None
    error_code: str | None = None


type OperationDetails = RagDetails | ToolDetails | SummaryDetails | WorkflowDetails
type OperationSnapshot = OperationRecord
