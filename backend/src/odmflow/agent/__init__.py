"""Agent 公共运行契约。

用途：导出调用方真正使用的运行端口和事件。
边界：不公开框架内部对象或在导入时构造模型。
"""

from .contracts import AgentStreamEvent
from .ports import AgentRunner

__all__ = ["AgentRunner", "AgentStreamEvent"]
