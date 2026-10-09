"""Agent 一轮流式执行用例。

用途：接受已验证消息，协调运行、失败保底与最终保存。
边界：不依赖 HTTP、LangChain 或 SQLAlchemy；不定义 ODM 规则。
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import replace

from odmflow.conversations import ConversationStorageUnavailable, Outcome, StartedTurn, TurnConflict
from odmflow.conversations.context_contracts import ContextRequest
from odmflow.conversations.operation_records import CitationSnapshot

from .contracts import (
    AcceptedTurnEvent,
    CompletedTurnEvent,
    EmptyAgentReply,
    OperationTurnEvent,
    TokenTurnEvent,
    TurnStorageErrorEvent,
    TurnStreamEvent,
)
from .failures import failure_reply
from .ports import (
    AgentAfterSalesPort,
    AgentApplicationPort,
    AgentContextPort,
    AgentConversationPort,
    AgentKnowledgePort,
    AgentOrderReadPort,
    AgentProfilePort,
    AgentRunner,
)
from .replies import build_partial_reply, prepare_reply
from .run_context import AgentRunContext
from .tracing.recorder import PersistedOperationRecorder
from .tracing.task_workflow import finalize_task_snapshot

logger = logging.getLogger(__name__)


class AgentTurnService:
    """一轮 Agent 执行协调器；存储与模型均通过端口注入。"""

    def __init__(
        self,
        runner: AgentRunner,
        conversations: AgentConversationPort,
        knowledge: AgentKnowledgePort | None = None,
        context_store: AgentContextPort | None = None,
        profile_store: AgentProfilePort | None = None,
        order_reader_factory: Callable[[str], AgentOrderReadPort] | None = None,
        action_factory: Callable[[ContextRequest], AgentApplicationPort] | None = None,
        after_sales_factory: Callable[[str], AgentAfterSalesPort] | None = None,
    ) -> None:
        """注入运行器与异步对话端口，不执行请求。

        Args:
            runner: 框架运行适配或测试替身。
            conversations: 接受消息和保存回复的异步端口。
            knowledge: 可选知识查询端口，不由模型选择当前账号。
            context_store: 可选的本账号/本会话摘要端口，不保存用户画像。
            profile_store: 本人画像端口；只放入本轮上下文，不在这里调用模型。
            order_reader_factory: 由服务器用可信owner构造的本人订单只读端口工厂。
        Returns:
            无；初始化用例。
        """
        self._runner = runner
        self._conversations = conversations
        self._knowledge = knowledge
        self._context_store = context_store
        self._profile_store = profile_store
        self._order_reader_factory = order_reader_factory
        self._action_factory = action_factory
        self._after_sales_factory = after_sales_factory

    async def start_turn(
        self, owner_id: str, conversation_id: str | None, client_turn_id: str, message: str
    ) -> StartedTurn:
        """提交用户消息；调用方须在开启 HTTP 流之前等待此步骤。

        Args:
            owner_id: 服务端已验证账号，不得来自模型参数。
            conversation_id: 既有对话或 None。
            client_turn_id: 请求唯一标识。
            message: 已校验文本。
        Returns:
            已提交运行与历史。
        Raises:
            ConversationNotFound: 对话不可见。
            DuplicateTurn: 请求重复。
            TurnConflict: 对话占用。
            ConversationStorageUnavailable: 未保存成功，不启动模型。
        """
        started = await self._conversations.start_turn(
            owner_id, conversation_id, client_turn_id, message
        )
        return replace(
            started,
            owner_id=owner_id,
            user_message=replace(started.user_message, turn_id=started.turn_id),
        )

    async def stream_turn(
        self, started: StartedTurn, message: str, is_disconnected: Callable[[], Awaitable[bool]]
    ) -> AsyncGenerator[TurnStreamEvent]:
        """运行模型并在最终保存后才声明完成。

        Args:
            started: 开始事务已提交的快照。
            message: 当前用户文本。
            is_disconnected: 由传输层提供的断连检查。
        Yields:
            接受、增量、真实工具、已保存完成或存储错误事件。
        Raises:
            asyncio.CancelledError: 尝试中断收口后继续传播取消。
        """
        yield AcceptedTurnEvent(started)
        outcome: Outcome = "completed"
        content = ""
        stop_reason: str | None = None
        recorder = PersistedOperationRecorder(self._conversations, started)
        context = AgentRunContext(recorder, self._knowledge)
        context.context_store = self._context_store
        context.profile_store = self._profile_store
        context.orders = (
            self._order_reader_factory(started.owner_id) if self._order_reader_factory else None
        )
        context.context_request = ContextRequest(
            started.owner_id, started.conversation_id, started.turn_id, started.user_message.id
        )
        context.actions = (
            self._action_factory(context.context_request) if self._action_factory else None
        )
        context.after_sales = (
            self._after_sales_factory(started.owner_id) if self._after_sales_factory else None
        )
        try:
            stream = self._runner.stream(
                message,
                started.history,
                context=context,
            )
            try:
                async for event in stream:
                    if await is_disconnected():
                        outcome = "interrupted"
                        stop_reason = "disconnected"
                        content = "连接中断，本轮回复未完成。请发送新的消息继续。"
                        break
                    if event.kind == "token":
                        yield TokenTurnEvent(event.text)
                    elif event.kind == "done":
                        content = event.text
                    elif (
                        event.kind in ("operation_started", "operation_finished")
                        and event.operation is not None
                    ):
                        yield OperationTurnEvent(event.kind, event.operation)
            finally:
                # 当前框架适配/替身均为异步生成器；其他迭代器没有关闭动作则不强制调用。
                closer = getattr(stream, "aclose", None)
                if closer is not None:
                    await closer()
            if not content:
                raise EmptyAgentReply
        except asyncio.CancelledError:
            try:
                await finalize_task_snapshot(context, "disconnected")
                await self._conversations.finish_turn(
                    started.turn_id, "连接中断，本轮回复未完成。请发送新的消息继续。", "interrupted"
                )
            except ConversationStorageUnavailable, TurnConflict:
                logger.warning("Conversation interrupted finalization failed")
            raise
        except Exception as error:
            stop_reason = "deadline" if isinstance(error, TimeoutError) else "no_progress"
            content = (
                ""
                if isinstance(error, ConversationStorageUnavailable)
                else build_partial_reply(
                    context.task_results,
                    "deadline" if isinstance(error, TimeoutError) else "no_progress",
                )
            )
            outcome = "completed" if content else "failed"
            content = content or failure_reply(error)
        try:
            if stop_reason:
                for event in await finalize_task_snapshot(context, stop_reason):
                    if event.operation and event.kind in {
                        "operation_started",
                        "operation_finished",
                    }:
                        yield OperationTurnEvent(event.kind, event.operation)
        except ConversationStorageUnavailable, TurnConflict:
            logger.warning("Task snapshot finalization storage failed")
            yield TurnStorageErrorEvent()
            return
        citations: tuple[CitationSnapshot, ...] = ()
        if outcome == "completed":
            content, citations = prepare_reply(content, context.rag_evidence)
        try:
            saved = await self._conversations.finish_turn(
                started.turn_id, content, outcome, citations
            )
        except ConversationStorageUnavailable, TurnConflict:
            logger.warning("Conversation finalization storage failed")
            yield TurnStorageErrorEvent()
            return
        yield CompletedTurnEvent(saved, outcome)
