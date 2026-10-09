"""用途：校验会话压缩和上下文预算；边界：只读配置，不调用模型，不把估算值当供应商精确token。"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ContextSettings:
    """有界摘要和输出预留策略；不控制长期画像或Embedding512token限额。"""

    enabled: bool = True
    window_tokens: int = 16384
    output_tokens: int = 2048
    keep_messages: int = 12
    trigger_messages: int = 24
    summary_tokens: int = 1024
    summary_timeout: float = 30
    max_batches: int = 2
    page_messages: int = 64

    def __post_init__(self) -> None:
        """校验预算、页大小和有限时限，非法配置启动时失败。"""
        if (
            not 4096 <= self.window_tokens <= 1000000
            or not 256 <= self.output_tokens < self.window_tokens - 1024
            or not 1 <= self.keep_messages < self.trigger_messages <= 64
            or not 128 <= self.summary_tokens <= 2048
            or self.summary_tokens >= self.input_budget // 2
            or not 1 <= self.max_batches <= 4
            or not self.trigger_messages <= self.page_messages <= 128
            or not math.isfinite(self.summary_timeout)
            or not 0 < self.summary_timeout <= 120
        ):
            raise ValueError("会话上下文预算配置无效")

    @property
    def input_budget(self) -> int:
        """返回扣除输出预留后的输入估算预算。"""
        return self.window_tokens - self.output_tokens
