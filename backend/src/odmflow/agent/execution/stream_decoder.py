"""用途：将框架三类流解码为内部事件。边界：不运行图、不做存储和业务判断。"""

from typing import Any

from langchain_core.messages import AIMessageChunk

from ..contracts import AgentStreamEvent


class GraphStreamDecoder:
    """每轮独立流状态，只保留非工具调用的最终助手回复。"""

    def __init__(self) -> None:
        """初始化本轮解码状态，不跨会话共享。"""
        self.final_reply = ""

    def consume(self, mode: str, update: Any) -> list[AgentStreamEvent]:
        """解码一项框架数据，Any只用于三类动态载荷边界。

        Args:
            mode: messages、updates或custom。
            update: 对应模式载荷。
        Returns:
            增量或自定义事件；最终消息另存final_reply。
        """
        if mode == "custom" and isinstance(update, AgentStreamEvent):
            return [update]
        if mode == "messages":
            chunk, metadata = update
            if (
                isinstance(chunk, AIMessageChunk)
                and metadata.get("langgraph_node") == "compose_reply"
            ):
                piece = str(chunk.text)
                return [AgentStreamEvent("token", text=piece)] if piece else []
        elif mode == "updates":
            for node, node_update in update.items():
                if node != "compose_reply":
                    continue
                if not isinstance(node_update, dict):
                    continue
                if isinstance(node_update.get("final_reply"), str):
                    self.final_reply = node_update["final_reply"].strip()
        return []
