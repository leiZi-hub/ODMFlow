"""用途：将本人订单只读业务适配为能力。边界：不接受身份、不推断无来源目标、不定义ORM。"""

from dataclasses import replace
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from odmflow.orders.domain import OrderReadUnavailable, OrderStatus

from ..run_context import AgentRunContext
from ..tasks.contracts import AgentTask, Capability, TaskResult
from .validation import mentions_exact_order_number


class ListMyOrdersInput(BaseModel):
    """本人列表可选状态，其他字段拒绝。"""

    model_config = ConfigDict(extra="forbid")
    status: OrderStatus | None = None


class GetMyOrderInput(BaseModel):
    """明确业务编号，绝不接受owner。"""

    model_config = ConfigDict(extra="forbid")
    order_no: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


async def execute_order_read(task: AgentTask, context: AgentRunContext) -> TaskResult:
    """只在本人绑定端口执行；分类异常返回有限重试标记。

    Args:
        task: 已通过schema、来源与调用预算门禁的任务。
        context: 由Session绑定的本人端口，模型无法覆盖owner。
    Returns:
        有界列表/详情/查无结果；明确断连故障返回可重试分类。"""
    if context.orders is None:
        return TaskResult(task.task_id, "unavailable", error_code="orders_unavailable")
    try:
        if task.capability == Capability.LIST_MY_ORDERS:
            payload = ListMyOrdersInput.model_validate(task.arguments)
            result = await context.orders.list_orders(payload.status)
            # 本人可见不等于用户选中了它；多笔列表不授权模型任意挑第一笔。
            latest_forms = {
                "查最新一笔订单",
                "查询最新订单",
                "查看最新一笔订单",
                "check my latest order",
            }
            current = (
                context.argument_evidence.user_messages[-1]
                if context.argument_evidence.user_messages
                else ""
            )
            latest_requested = current.strip(" \t\n。！？.!?").lower() in latest_forms
            derived = (
                result.items[:1]
                if latest_requested
                else result.items
                if len(result.items) == 1 and not result.has_more
                else ()
            )
            context.argument_evidence = replace(
                context.argument_evidence,
                known_order_nos=context.argument_evidence.known_order_nos
                | frozenset(item.order_no for item in derived),
            )
            return TaskResult(
                task.task_id, "ok" if result.items else "empty", result.model_dump(mode="json")
            )
        order_no = GetMyOrderInput.model_validate(task.arguments).order_no
        evidence = context.argument_evidence
        if order_no not in evidence.known_order_nos and not mentions_exact_order_number(
            order_no, evidence.user_messages
        ):
            return TaskResult(task.task_id, "needs_input", error_code="order_target_not_grounded")
        detail = await context.orders.get_order(order_no)
        return TaskResult(task.task_id, detail.code, detail.model_dump(mode="json"))
    except OrderReadUnavailable as error:
        return TaskResult(
            task.task_id,
            "unavailable",
            error_code="order_read_unavailable",
            retryable=error.retryable,
        )
