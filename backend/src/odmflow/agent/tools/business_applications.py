"""用途：受控准备能力适配；边界：不包含SQL、确认、执行或用户ID参数。"""

from odmflow.business_actions.domain import ActionConflict, ActionNotFound

from ..run_context import AgentRunContext
from ..tasks.contracts import AgentTask, Capability, TaskResult
from .validation import mentions_exact_order_number


async def execute_application(task: AgentTask, context: AgentRunContext) -> TaskResult:
    """准备一张真实卡；来源/归属失败要求澄清，不自动重试写预览。"""
    if context.actions is None:
        return TaskResult(task.task_id, "unavailable", error_code="applications_unavailable")
    if context.application_prepared:
        return TaskResult(task.task_id, "needs_input", error_code="one_write_preview_per_turn")
    after = task.capability == Capability.PREPARE_AFTER_SALES_APPLICATION
    if after:
        number = task.arguments.get("order_no")
        evidence = context.argument_evidence
        if not isinstance(number, str) or (
            number not in evidence.known_order_nos
            and not mentions_exact_order_number(number, evidence.user_messages)
        ):
            return TaskResult(task.task_id, "needs_input", error_code="order_target_not_grounded")
    try:
        view = await context.actions.prepare(
            "after_sales_application" if after else "order_application", task.arguments
        )
    except ActionNotFound, ActionConflict:
        return TaskResult(task.task_id, "needs_input", error_code="application_not_eligible")
    context.application_prepared = True
    return TaskResult(task.task_id, "awaiting_confirmation", view.model_dump(mode="json"))
