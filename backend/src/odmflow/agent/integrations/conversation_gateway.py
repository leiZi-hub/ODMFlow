"""对话线程池适配器。

用途：将完整同步对话用例转为异步调用，不阻塞主事件循环。
边界：不创建 ORM 会话、不拆事务、不改变对话业务错误。
"""

from dataclasses import replace

from starlette.concurrency import run_in_threadpool

from odmflow.conversations import ConversationService, MessageView, Outcome, StartedTurn
from odmflow.conversations.operation_records import CitationSnapshot, OperationRecord

from ..memory.history_policy import HISTORY_CANDIDATE_LIMIT, clip_recent_history


class ThreadedConversationGateway:
    """Agent 存储端口的线程池实现，依赖对话公共服务。"""

    def __init__(self, service: ConversationService) -> None:
        """注入同步服务；构造时不进行存储操作。

        Args:
            service: 已组装仓储的对话公共服务。
        Returns:
            无；初始化线程池适配。
        """
        self._service = service

    async def start_turn(
        self, owner_id: str, conversation_id: str | None, client_turn_id: str, message: str
    ) -> StartedTurn:
        """在线程池执行完整开始用例。

        Args:
            owner_id: 已验证账号。
            conversation_id: 对话标识或 None。
            client_turn_id: 请求唯一标识。
            message: 用户文本。
        Returns:
            已提交的运行快照。
        Raises:
            ConversationStorageUnavailable: 存储失败；其他对话领域错误原样传播。
        """
        started = await run_in_threadpool(
            self._service.start_turn,
            owner_id,
            conversation_id,
            client_turn_id,
            message,
            history_limit=HISTORY_CANDIDATE_LIMIT,
        )
        return replace(started, history=clip_recent_history(started.history))

    async def finish_turn(
        self,
        turn_id: str,
        content: str,
        outcome: Outcome,
        citations: tuple[CitationSnapshot, ...] = (),
    ) -> MessageView:
        """在线程池执行完整最终保存。

        Args:
            turn_id: 运行标识。
            content: 完整回复或保底。
            outcome: 运行终态。
        Returns:
            已提交消息。
        Raises:
            ConversationStorageUnavailable: 保存失败。
            TurnConflict: 运行已终结。
        """
        return await run_in_threadpool(
            self._service.finish_turn, turn_id, content, outcome, citations
        )

    async def start_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """在线程池等待开始快照完整提交。

        Args:
            owner_id: 已验证主体。
            conversation_id: 当前对话。
            turn_id: 当前轮次。
            record: 要保存的开始快照。
        Returns:
            已提交操作。
        """
        return await run_in_threadpool(
            self._service.start_operation, owner_id, conversation_id, turn_id, record
        )

    async def finish_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """在线程池等待操作终态快照提交。

        Args:
            owner_id: 已验证主体。
            conversation_id: 当前对话。
            turn_id: 当前轮次。
            record: 完整终态快照。
        Returns:
            已提交终态。
        """
        return await run_in_threadpool(
            self._service.finish_operation, owner_id, conversation_id, turn_id, record
        )
