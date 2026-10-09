"""用途：表达框架工具适配签名。边界：不放领域schema、业务规则或全局状态。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel

from ..tasks.contracts import AgentTask, Capability, TaskResult

if TYPE_CHECKING:
    from ..run_context import AgentRunContext


class CapabilityRisk(StrEnum):
    """由服务器登记的只读风险类别；本阶段没有写能力。"""

    PUBLIC_KNOWLEDGE = "public_knowledge"
    READONLY_COMPUTATION = "readonly_computation"
    PRIVATE_READONLY = "private_readonly"
    PRIVATE_AFTER_SALES_READ = "private_after_sales_read"
    CONFIRMATION_REQUIRED = "confirmation_required"


@dataclass(frozen=True)
class CapabilityDefinition:
    """能力、参数契约及真实适配入口；不执行目录扫描。"""

    name: Capability
    input_schema: type[BaseModel]
    risk: CapabilityRisk
    description: str
    execute: Callable[[AgentTask, AgentRunContext], Awaitable[TaskResult]]
