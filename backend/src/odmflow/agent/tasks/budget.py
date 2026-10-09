"""用途：维护本轮单调预算与去重账本。边界：不判断模型意图或业务错误类型。"""

from dataclasses import dataclass, field

from .configuration import TaskSettings


class TaskLimitExceeded(ValueError):
    """受控限额/重复调用拒绝，不包含敏感参数。"""


@dataclass
class TaskBudget:
    """一轮独立账本，计划修正不能重新创建它。"""

    settings: TaskSettings
    model_calls: int = 0
    capability_calls: int = 0
    repairs: int = 0
    replans: int = 0
    readonly_retries: int = 0
    called_keys: set[str] = field(default_factory=set)
    retried_keys: set[str] = field(default_factory=set)

    def consume_model(self, *, final: bool = False) -> None:
        """扣除模型额度。Args: final: 最终回答可使用预留一次。

        Raises: TaskLimitExceeded: 无剩余额度；失败不修改计数。
        """
        maximum = self.settings.max_model_calls - (0 if final else 1)
        if self.model_calls >= maximum:
            raise TaskLimitExceeded("graph_model_budget_exhausted")
        self.model_calls += 1

    def consume_capability(self, key: str, *, retry: bool = False) -> None:
        """扣除真实调用额度。Args: key: 规范化目标摘要；retry: 获准瞬时重试。

        Raises: TaskLimitExceeded: 目标重复、未获重试额度或总额耗尽。
        """
        if self.capability_calls >= self.settings.max_capability_calls:
            raise TaskLimitExceeded("capability_budget_exhausted")
        if retry:
            if key not in self.called_keys or key in self.retried_keys or not self.readonly_retries:
                raise TaskLimitExceeded("readonly_retry_not_granted")
            self.retried_keys.add(key)
        elif key in self.called_keys:
            raise TaskLimitExceeded("duplicate_capability_call")
        self.called_keys.add(key)
        self.capability_calls += 1

    def consume_repair(self) -> None:
        """扣除全轮唯一纠正机会。Raises: TaskLimitExceeded: 已使用或禁用。"""
        if self.repairs >= self.settings.max_argument_repairs:
            raise TaskLimitExceeded("argument_repair_exhausted")
        self.repairs += 1

    def consume_replan(self) -> None:
        """扣除全轮唯一计划修正。Raises: TaskLimitExceeded: 已使用或禁用。"""
        if self.replans >= self.settings.max_replans:
            raise TaskLimitExceeded("replan_exhausted")
        self.replans += 1

    def consume_readonly_retry(self) -> None:
        """许可一次只读追加尝试。Raises: TaskLimitExceeded: 禁用或已使用。"""
        if not self.settings.order_read_retry_enabled or self.readonly_retries >= 1:
            raise TaskLimitExceeded("readonly_retry_exhausted")
        self.readonly_retries += 1
