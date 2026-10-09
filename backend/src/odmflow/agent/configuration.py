"""用途：统一模型网络等待与 Agent 整轮时限；边界：只读配置，不调用模型或数据库。"""

import math
from dataclasses import dataclass
from datetime import timedelta

DEFAULT_LLM_TIMEOUT_SECONDS = 120.0
DEFAULT_AGENT_TIMEOUT_SECONDS = 300.0


@dataclass(frozen=True)
class AgentTimeoutSettings:
    """模型网络等待、整轮硬截止与恢复宽限；不控制自动重试或工具调用次数。"""

    llm_request_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    turn_seconds: float = DEFAULT_AGENT_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        """拒绝无界/非正等待和小于单次等待的整轮预算。"""
        for name, value in (
            ("model.request_timeout_seconds", self.llm_request_seconds),
            ("agent.turn_timeout_seconds", self.turn_seconds),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        if self.turn_seconds < self.llm_request_seconds:
            raise ValueError("agent.turn_timeout_seconds must be >= model.request_timeout_seconds")

    def recovery_after(self) -> timedelta:
        """返回整轮时限加60秒存储/调度宽限，避免正常慢回复被残留恢复提前终结。

        Returns:
            用于对话仓储过期筛选的时长，不是另一次模型调用预算。
        """
        return timedelta(seconds=self.turn_seconds + 60)


@dataclass(frozen=True)
class RagRuntimeSettings:
    """在线知识查询预算；不负责离线模型路径或检索引擎模式。"""

    timeout_seconds: float = 5
    top_k: int = 3
    max_context_chars: int = 6000
    max_distance: float | None = None

    def __post_init__(self) -> None:
        """保持现行在线预算与距离范围，无效配置显式失败。"""
        from odmflow.knowledge.domain import KnowledgeError

        if (
            not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
            or not 1 <= self.top_k <= 3
            or not 1 <= self.max_context_chars <= 24000
        ):
            raise KnowledgeError("知识预算配置非法")
        if self.max_distance is not None and (
            not math.isfinite(self.max_distance) or self.max_distance < 0
        ):
            raise KnowledgeError("知识距离阈值配置非法")
