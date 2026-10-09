"""用途：协调每轮历史读取、摘要准备及真实操作事件。边界：不运行主图、不写SQL，状态不可跨请求复用。"""

from collections.abc import AsyncGenerator, Awaitable, Callable

from odmflow.conversations import ConversationStorageUnavailable
from odmflow.conversations.context_contracts import ContextMessage

from ..contracts import AgentStreamEvent
from ..run_context import AgentRunContext
from ..tracing.operations import (
    OperationDescriptor,
    OperationKind,
    OperationName,
    OperationStatus,
    SummaryDetails,
)
from .configuration import ContextSettings
from .preparation import PreparedContext, needs_summary, prepare_context


class ContextPreparation:
    """一个请求的记忆准备协调器；输出prepared与已保存的摘要生命周期事件。"""

    def __init__(
        self,
        history: list[tuple[str, str]],
        settings: ContextSettings,
        signature: str,
        summarize: Callable[[str, tuple[ContextMessage, ...]], Awaitable[str]],
    ) -> None:
        """注入回退历史、策略、摘要版本和一次模型适配；不执行IO。

        Args:
            history: Agent裁剪后的升序完整回退历史。
            settings: 保持现行阈值的记忆策略。
            signature: 摘要模型/模板签名。
            summarize: 独立摘要调用适配。
        """
        self.prepared = PreparedContext(history=history)
        self._settings, self._signature, self._summarize = settings, signature, summarize

    async def events(
        self, message: str, context: AgentRunContext
    ) -> AsyncGenerator[AgentStreamEvent]:
        """读取摘要并按需整理；开始事件先于模型等待，结束事件先于主图。

        Args:
            message: 当前消息，用于预算和触发评估。
            context: 当前轮的可信摘要端口与操作记录器。
        Yields:
            已持久化的摘要开始/结束事件；无摘要时不伪造事件。
        Raises:
            Exception: 操作保存失败等非降级错误交给整轮用例收口。
        """
        if (
            not self._settings.enabled
            or context.context_store is None
            or context.context_request is None
        ):
            return
        try:
            snapshot = await context.context_store.load(
                context.context_request,
                limit=self._settings.page_messages,
                keep=self._settings.keep_messages,
                signature=self._signature,
            )
        except ConversationStorageUnavailable:
            self.prepared = PreparedContext(
                history=self.prepared.history,
                notice="较早内容暂未完整整理，本轮仅使用近期对话。\n\n",
            )
            return
        operation = None
        if needs_summary(snapshot, self._settings, message):
            operation = await context.operations.start(
                OperationDescriptor(OperationKind.CONTEXT, OperationName.SUMMARIZE_CONTEXT),
                SummaryDetails(pending_messages=len(snapshot.pending), has_more=snapshot.has_more),
            )
            yield AgentStreamEvent("operation_started", operation=operation)
        self.prepared = await prepare_context(
            snapshot,
            context.context_request,
            context.context_store,
            self._summarize,
            self._settings,
            message,
            self._signature,
        )
        if operation is not None:
            failed = bool(self.prepared.notice and not self.prepared.batches)
            finished = await context.operations.finish(
                operation.id,
                OperationStatus.FAILED if failed else OperationStatus.COMPLETED,
                SummaryDetails(
                    batches=self.prepared.batches,
                    recent_messages=len(self.prepared.history),
                    degraded=bool(self.prepared.notice),
                    summary=self.prepared.summary,
                    error_code="summary_unavailable" if failed else None,
                ),
            )
            yield AgentStreamEvent("operation_finished", operation=finished)
