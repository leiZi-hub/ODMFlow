"""Agent 应用端口。

用途：定义运行器和异步对话操作，供真实适配和测试替身实现。
边界：不引入 HTTP、ORM 或模型框架。
"""

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol

from odmflow.after_sales.domain import AfterSalesList, AfterSalesLookup
from odmflow.business_actions.domain import ActionView
from odmflow.conversations import MessageView, Outcome, StartedTurn
from odmflow.conversations.context_contracts import (
    ContextHistory,
    ContextRequest,
    ConversationSummarySnapshot,
)
from odmflow.conversations.operation_records import CitationSnapshot, JsonValue, OperationRecord
from odmflow.orders.domain import OrderList, OrderLookup, OrderStatus
from odmflow.profiles import ProfileCandidate, ProfileInputSnapshot, ProfileSnapshot

from .contracts import AgentStreamEvent
from .tools.rag.evidence import PreparedKnowledge
from .tracing.operations import (
    OperationDescriptor,
    OperationDetails,
    OperationSnapshot,
    OperationStatus,
)

if TYPE_CHECKING:
    from .run_context import AgentRunContext


class AgentProfilePort(Protocol):
    """受控画像读取/候选保存，不暴露数据库或允许模型自行写入。"""

    async def load_sources(self, request: ContextRequest, limit: int) -> ProfileInputSnapshot:
        """读取本人画像及当前会话有界原始用户消息。"""
        ...

    async def apply_candidates(
        self,
        request: ContextRequest,
        snapshot: ProfileInputSnapshot,
        candidates: tuple[ProfileCandidate, ...],
    ) -> ProfileSnapshot:
        """按来源和版本验证整批候选，返回提交后的有效画像。"""
        ...


class AgentContextPort(Protocol):
    """有界摘要快照和CAS持久化；不生成摘要或暴露SQLSession。"""

    async def load(
        self, request: ContextRequest, limit: int, keep: int, signature: str
    ) -> ContextHistory:
        """返回已授权的有界历史及有效摘要，失败传播领域错误。"""
        ...

    async def save(
        self,
        request: ContextRequest,
        history: ContextHistory,
        text: str,
        through_id: int,
        signature: str,
    ) -> ConversationSummarySnapshot:
        """原子核验来源及版本后保存，返回已提交快照。"""
        ...


class AgentOperationRecorder(Protocol):
    """每轮注入的保存门禁，工具执行前必须等待开始事务成功。"""

    async def start(
        self, descriptor: OperationDescriptor, details: OperationDetails
    ) -> OperationSnapshot:
        """提交开始快照并返回已保存ID/序号。"""
        ...

    async def finish(
        self, operation_id: str, status: OperationStatus, details: OperationDetails
    ) -> OperationSnapshot:
        """提交完整终态后才允许发公开结束事件。"""
        ...


class AgentKnowledgePort(Protocol):
    """异步知识查询边界，不暴露具体模型/向量库。"""

    async def validate_query(self, query: str) -> None:
        """工具执行前检查长度，超限只保存失败尝试、不运行编码或检索。"""
        ...

    async def retrieve(self, query: str) -> PreparedKnowledge:
        """有预算地编码/查询/整理，不阻塞事件循环。"""
        ...


class AgentRunner(Protocol):
    """流式 Agent 调用边界；测试替身与真实服务共享同一契约。"""

    def stream(
        self,
        message: str,
        history: list[tuple[str, str]],
        *,
        context: AgentRunContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        """将当前消息与有限历史传入增量运行；实现可以是真实图或替身。

        Args:
            message: 当前用户文本。
            history: 经过预算限制的升序正常历史。
            context: 服务端每轮创建的端口、预算和证据。
        Returns:
            增量事件迭代器；消费时的运行错误交由应用层处理。
        """


class AgentConversationPort(Protocol):
    """Agent 用例所需异步存储边界，不暴露数据库类型。"""

    async def start_turn(
        self, owner_id: str, conversation_id: str | None, client_turn_id: str, message: str
    ) -> StartedTurn:
        """按可信账号接受消息，等待原子开始事务完成。

        Args:
            owner_id: 服务端验证账号。
            conversation_id: 既有对话，None 新建。
            client_turn_id: 请求唯一标识。
            message: 用户文本。
        Returns:
            已提交运行快照。
        Raises:
            ConversationNotFound: 资源不可见。
            DuplicateTurn: 请求重复。
            TurnConflict: 对话占用。
            ConversationStorageUnavailable: 存储失败。
        """
        ...

    async def finish_turn(
        self,
        turn_id: str,
        content: str,
        outcome: Outcome,
        citations: tuple[CitationSnapshot, ...] = (),
    ) -> MessageView:
        """等待最终事务成功保存并释放运行占用。

        Args:
            turn_id: 运行标识。
            content: 完整回复或保底。
            outcome: 运行终态。
        Returns:
            已保存的助手消息快照。
        Raises:
            TurnConflict: 运行已终结。
            ConversationStorageUnavailable: 最终保存失败。
        """
        ...

    async def start_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """异步等待完整开始事务。"""
        ...

    async def finish_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """异步等待完整操作终结事务。"""
        ...


class AgentOrderReadPort(Protocol):
    """本人绑定的实际异步IO边界；接口不接受owner。"""

    async def list_orders(self, status: OrderStatus | None = None) -> OrderList: ...

    async def get_order(self, order_no: str) -> OrderLookup: ...


class AgentApplicationPort(Protocol):
    """真实异步准备边界，接口没有确认/身份字段。"""

    async def prepare(self, kind: str, parameters: dict[str, JsonValue]) -> ActionView:
        """返回本人来源轮的真实待确认快照。"""
        ...


class AgentAfterSalesPort(Protocol):
    """本人售后只读边界。"""

    async def list(self) -> AfterSalesList:
        """读取有界列表。"""
        ...

    async def get(self, application_no: str) -> AfterSalesLookup:
        """读取明确本人申请编号。"""
        ...
