"""Agent 框架无关事件契约。

用途：定义运行器与应用用例传递的类型事件。
边界：不处理 HTTP、数据库或工具注册。
"""

from dataclasses import dataclass
from typing import Literal

from odmflow.conversations import MessageView, Outcome, StartedTurn
from odmflow.conversations.operation_records import OperationRecord
from odmflow.knowledge.domain import KnowledgeError


@dataclass(frozen=True)
class AgentStreamEvent:
    """Agent 的增量文字、真实工具执行或最终完整文字。"""

    kind: Literal["token", "done", "operation_started", "operation_finished"]
    text: str = ""
    operation: OperationRecord | None = None


class ContextBudgetExceeded(Exception):
    """当前问题/系统规则/完整工具协议已无法满足输入预算，不再调用模型。"""


class ContextSummaryFailed(Exception):
    """摘要无法安全使用；不携带供应商原始响应，允许窗口降级。"""


class EmptyAgentReply(Exception):
    """表示模型结束运行却没有可展示的文本回复。"""


class QueryCompactionFailed(KnowledgeError):
    """单次检索问题精简失败；错误码用于真实操作记录，不携带 SDK 异常。"""

    def __init__(self, code: str = "query_compaction_failed") -> None:
        """保存安全错误码，不包含原始供应商响应或请求配置。

        Args:
            code: 服务端确定的精简失败分类。
        """
        super().__init__("本轮未能精简检索问题")
        self.code = code


@dataclass(frozen=True)
class AcceptedTurnEvent:
    """开始事务已提交的消息事件；历史仅供内部使用。"""

    started: StartedTurn


@dataclass(frozen=True)
class TokenTurnEvent:
    """尚未持久化的模型文本增量。"""

    text: str


@dataclass(frozen=True)
class CompletedTurnEvent:
    """最终事务提交后的可见助手消息。"""

    assistant_message: MessageView
    outcome: Outcome


@dataclass(frozen=True)
class OperationTurnEvent:
    """已提交的操作生命周期，供传输层统一权限投影。"""

    name: Literal["operation_started", "operation_finished"]
    operation: OperationRecord


@dataclass(frozen=True)
class TurnStorageErrorEvent:
    """最终保存失败；不能把流过的文字当作已保存。"""

    code: Literal["storage_unavailable"] = "storage_unavailable"


type TurnStreamEvent = (
    AcceptedTurnEvent
    | TokenTurnEvent
    | OperationTurnEvent
    | CompletedTurnEvent
    | TurnStorageErrorEvent
)
