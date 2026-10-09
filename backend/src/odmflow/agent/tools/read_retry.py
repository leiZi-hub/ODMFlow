"""用途：判断已结束的本人只读故障是否可重试。边界：不重试模型、RAG或未知异常。"""

from ..tasks.budget import TaskBudget
from ..tasks.contracts import TaskResult


class ReadRetryPolicy:
    """全轮一次、短退避的服务器瞬时故障策略。"""

    def should_retry(
        self, result: TaskResult, attempt: int, budget: TaskBudget, remaining_seconds: float
    ) -> bool:
        """仅在下游明确标记瞬时故障、预算及时间充足时允许追加一次。"""
        return (
            result.code == "unavailable"
            and result.retryable
            and attempt == 1
            and budget.settings.order_read_retry_enabled
            and budget.readonly_retries == 0
            and budget.capability_calls < budget.settings.max_capability_calls
            and remaining_seconds > 0.1
        )
