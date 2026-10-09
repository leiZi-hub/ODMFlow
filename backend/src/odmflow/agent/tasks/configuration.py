"""用途：读取有限任务预算。边界：无IO，不允许配置扩大硬上限。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskSettings:
    """图内预算，与记忆准备计数分开；整轮deadline仍由runner控制。"""

    max_tasks: int = 4
    max_capability_calls: int = 4
    max_model_calls: int = 4
    max_replans: int = 1
    max_argument_repairs: int = 1
    order_read_retry_enabled: bool = True

    def __post_init__(self) -> None:
        """校验范围，避免零额度或任意大值绕过服务器策略。"""
        for name, minimum, maximum in (
            ("max_tasks", 1, 4),
            ("max_capability_calls", 1, 4),
            ("max_model_calls", 2, 4),
            ("max_replans", 0, 1),
            ("max_argument_repairs", 0, 1),
        ):
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError(f"Invalid task limit: {name}")
