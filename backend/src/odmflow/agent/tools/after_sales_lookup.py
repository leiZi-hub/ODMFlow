"""用途：本人售后读能力；边界：不选身份、不审批退换，不猜业务编号。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from ..run_context import AgentRunContext
from ..tasks.contracts import AgentTask, Capability, TaskResult
from .validation import mentions_exact_order_number


class ListMyAfterSalesInput(BaseModel):
    """有界本人列表，无额外参数。"""

    model_config = ConfigDict(extra="forbid")


class GetMyAfterSalesInput(BaseModel):
    """用户明确的受理编号，不接收身份。"""

    model_config = ConfigDict(extra="forbid")
    application_no: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
    ]


async def execute_after_sales_read(task: AgentTask, context: AgentRunContext) -> TaskResult:
    """读取本人实际受理结果，未知编号先澄清；不添加隐藏重试。"""
    if context.after_sales is None:
        return TaskResult(task.task_id, "unavailable", error_code="after_sales_unavailable")
    if task.capability == Capability.LIST_MY_AFTER_SALES:
        listing = await context.after_sales.list()
        return TaskResult(
            task.task_id, "ok" if listing.items else "empty", listing.model_dump(mode="json")
        )
    number = GetMyAfterSalesInput.model_validate(task.arguments).application_no
    if not mentions_exact_order_number(number, context.argument_evidence.user_messages):
        return TaskResult(task.task_id, "needs_input", error_code="application_target_not_grounded")
    detail = await context.after_sales.get(number)
    return TaskResult(task.task_id, detail.code, detail.model_dump(mode="json"))
