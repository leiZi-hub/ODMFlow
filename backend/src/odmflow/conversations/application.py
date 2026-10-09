"""对话应用用例。

用途：协调存储端口、有界完整历史和残留运行恢复策略。
边界：不导入 SQLAlchemy，不直接操作 HTTP 或调用模型。
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .domain import ConversationPage, MessagePage, MessageView, Outcome, StartedTurn, TurnConflict
from .operation_records import CitationSnapshot, OperationRecord
from .ports import ConversationRepository


class ConversationService:
    """私人对话用例；原子存储交给仓储，策略留在本层。"""

    def __init__(
        self, repository: ConversationRepository, stale_after: timedelta = timedelta(minutes=2)
    ) -> None:
        """注入同步仓储与残留运行阈值，不持有数据库会话。

        Args:
            repository: 原子存储端口或测试替身。
            stale_after: 未完成运行允许保留的时长。
        Returns:
            无；初始化策略服务。
        """
        self._repository = repository
        self._stale_after = stale_after

    def start_turn(
        self,
        owner_id: str,
        conversation_id: str | None,
        client_turn_id: str,
        message: str,
        *,
        history_limit: int = 20,
    ) -> StartedTurn:
        """接受消息并返回有界完整原始历史，不决定模型字符预算。

        Args:
            owner_id: 服务端已验证账号。
            conversation_id: 对话标识，None 表示新建。
            client_turn_id: 客户端请求唯一标识。
            message: 已校验文本。
            history_limit: 本次读取候选上限，由调用者指定，不是模型token预算。
        Returns:
            已提交运行和按时间升序的有限历史。
        Raises:
            ConversationNotFound: 对话未知或归属不符。
            DuplicateTurn: 请求已使用。
            TurnConflict: 对话正在运行。
            ConversationStorageUnavailable: 未成功保存。
        """
        accepted = self._repository.accept_turn(
            owner_id,
            conversation_id,
            str(uuid4()),
            client_turn_id,
            message,
            message[:120],
            datetime.now(UTC),
            history_limit,
        )
        return StartedTurn(
            accepted.turn_id,
            accepted.conversation_id,
            accepted.user_message,
            list(reversed(accepted.history_candidates)),
        )

    def finish_turn(
        self,
        turn_id: str,
        content: str,
        outcome: Outcome,
        citations: tuple[CitationSnapshot, ...] = (),
    ) -> MessageView:
        """提交唯一终态回复。

        Args:
            turn_id: 已提交运行标识。
            content: 最终回复或保底文本。
            outcome: 终态。
        Returns:
            已成功保存的消息快照。
        Raises:
            TurnConflict: 运行不存在或已终结。
            ConversationStorageUnavailable: 写入失败。
        """
        return self._repository.finish_turn(turn_id, content, outcome, datetime.now(UTC), citations)

    def start_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """保存开始快照后才允许操作执行；不持有数据库连接。

        Args:
            owner_id: 已验证主体。
            conversation_id: 当前私人对话。
            turn_id: 已接受的运行。
            record: 通用版本快照。
        Returns:
            已提交快照。
        """
        return self._repository.start_operation(owner_id, conversation_id, turn_id, record)

    def finish_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """提交操作终态，不等同于整轮回复完成。

        Args:
            owner_id: 已验证主体。
            conversation_id: 当前对话。
            turn_id: 当前轮次。
            record: 完整替换的终态快照。
        Returns:
            已提交终态。
        """
        return self._repository.finish_operation(owner_id, conversation_id, turn_id, record)

    def list_operations(
        self, owner_id: str, conversation_id: str, turn_id: str
    ) -> tuple[OperationRecord, ...]:
        """核对私人归属后读取操作，不调用工具/模型。

        Args:
            owner_id: 登录主体。
            conversation_id: 查询对话。
            turn_id: 需要属于该对话的轮次。
        Returns:
            按序排列的内部快照；API再做权限投影。
        """
        self.recover_stale_turns(owner_id)
        return self._repository.list_operations(owner_id, conversation_id, turn_id)

    def list_conversations(self, owner_id: str, limit: int, offset: int) -> ConversationPage:
        """恢复账号残留运行后返回分页对话快照。

        Args:
            owner_id: 当前账号。
            limit: 页大小。
            offset: 偏移。
        Returns:
            按更新时间倒序的对话页。
        Raises:
            ConversationStorageUnavailable: 存储失败。
        """
        self.recover_stale_turns(owner_id)
        return self._repository.list_conversations(owner_id, limit, offset)

    def list_messages(
        self, owner_id: str, conversation_id: str, limit: int, before_id: int | None
    ) -> MessagePage:
        """恢复残留运行并查询私人消息。

        Args:
            owner_id: 当前账号。
            conversation_id: 查询对话。
            limit: 页大小。
            before_id: 向前翻页游标。
        Returns:
            升序消息页与更早游标。
        Raises:
            ConversationNotFound: 对话未知或不属于账号。
            ConversationStorageUnavailable: 存储失败。
        """
        self.recover_stale_turns(owner_id)
        return self._repository.list_messages(owner_id, conversation_id, limit, before_id)

    def recover_stale_turns(self, owner_id: str) -> None:
        """将本账号过期运行收口；并发已终结的运行可忽略。

        Args:
            owner_id: 当前账号。
        Returns:
            无；符合恢复条件的运行会写入中断保底。
        Raises:
            ConversationStorageUnavailable: 恢复写入失败。
        """
        stale = self._repository.find_stale_turn_ids(
            owner_id, datetime.now(UTC) - self._stale_after
        )
        for turn_id in stale:
            try:
                self.finish_turn(
                    turn_id, "本轮运行中断，回复未完成。请发送新的消息继续。", "interrupted"
                )
            except TurnConflict:
                continue
