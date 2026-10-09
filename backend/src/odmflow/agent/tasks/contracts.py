"""用途：定义规划草案、可信任务和结果。边界：意图不是权限，不包含框架或SQL。"""

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from odmflow.conversations.operation_records import JsonValue


class TaskIntent(StrEnum):
    """有限处理类别，由模型建议、服务器检查。"""

    GENERAL_CHAT = "GENERAL_CHAT"
    KNOWLEDGE_QA = "KNOWLEDGE_QA"
    REQUIREMENT_ASSESSMENT = "REQUIREMENT_ASSESSMENT"
    OWN_ORDER_LOOKUP = "OWN_ORDER_LOOKUP"
    OWN_AFTER_SALES_LOOKUP = "OWN_AFTER_SALES_LOOKUP"
    ORDER_APPLICATION = "ORDER_APPLICATION"
    AFTER_SALES_APPLICATION = "AFTER_SALES_APPLICATION"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"


class Capability(StrEnum):
    """当前服务器实现的能力名，没有写业务或跨用户查询。"""

    RAG_SEARCH = "rag_search"
    ASSESS_ODM_REQUIREMENTS = "assess_odm_requirements"
    LIST_MY_ORDERS = "list_my_orders"
    GET_MY_ORDER = "get_my_order"
    LIST_MY_AFTER_SALES = "list_my_after_sales"
    GET_MY_AFTER_SALES = "get_my_after_sales"
    PREPARE_ORDER_APPLICATION = "prepare_order_application"
    PREPARE_AFTER_SALES_APPLICATION = "prepare_after_sales_application"


class TaskStatus(StrEnum):
    """程序维护的任务状态，不接受模型自报完成。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    WAITING_CONFIRMATION = "waiting_confirmation"
    FAILED = "failed"
    BLOCKED = "blocked"


class TaskDraft(BaseModel):
    """模型提出的有限目标；key只是草案引用，没有身份或状态权限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=40)
    intent: TaskIntent
    capability: Capability | None = None
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    depends_on: tuple[str, ...] = ()


class PlanDraft(BaseModel):
    """一次规划的有限任务集合，拒绝额外控制字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    tasks: tuple[TaskDraft, ...] = Field(min_length=1, max_length=4)


@dataclass(frozen=True)
class AgentTask:
    """服务器生成的任务快照，参数JSON避免外部修改嵌套集合。"""

    task_id: str
    intent: TaskIntent
    capability: Capability | None
    arguments_json: str
    depends_on: tuple[str, ...] = ()
    status: TaskStatus = TaskStatus.PENDING
    plan_key: str = ""
    error_code: str | None = None

    @property
    def arguments(self) -> dict[str, JsonValue]:
        """读取独立参数副本。Returns: 不共享可变集合的业务参数。"""
        return cast(dict[str, JsonValue], json.loads(self.arguments_json))


type ResultCode = Literal[
    "ok",
    "empty",
    "not_found",
    "invalid_arguments",
    "unavailable",
    "needs_input",
    "awaiting_confirmation",
]


@dataclass(frozen=True)
class TaskResult:
    """实际能力结果，retryable只由服务器错误分类赋值。"""

    task_id: str
    code: ResultCode
    data: JsonValue = None
    error_code: str | None = None
    sources: tuple[str, ...] = ()
    retryable: bool = False


@dataclass(frozen=True)
class ArgumentIssue:
    """安全的字段错误，不包含原始凭据或身份值。"""

    field_path: tuple[str | int, ...]
    code: str
    repairable: bool


@dataclass(frozen=True)
class ArgumentEvidence:
    """本人原话与本人查询目标，供有限重新抽取使用。"""

    user_messages: tuple[str, ...] = ()
    known_order_nos: frozenset[str] = frozenset()
