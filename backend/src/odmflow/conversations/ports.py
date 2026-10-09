"""对话仓储端口。

用途：定义原子业务存储操作和脱离数据库的结果。
边界：不暴露 SQL、ORM 或数据库会话。
"""

from datetime import datetime
from typing import Protocol

from .domain import AcceptedTurn, ConversationPage, MessagePage, MessageView, Outcome
from .operation_records import CitationSnapshot, OperationRecord


class ConversationRepository(Protocol):
    """应用层依赖的同步存储契约；每次写入应完整提交或回滚。"""

    def accept_turn(
        self,
        owner_id: str,
        conversation_id: str | None,
        new_conversation_id: str,
        client_turn_id: str,
        message: str,
        title: str,
        now: datetime,
        history_limit: int,
    ) -> AcceptedTurn:
        """提交用户消息与运行，返回有限历史候选。

        Args:
            owner_id: 服务端验证的账号标识。
            conversation_id: 既有对话，或 None 创建新对话。
            new_conversation_id: 新对话使用的标识。
            client_turn_id: 本次请求的唯一标识。
            message: 已校验的用户文本。
            title: 新对话标题。
            now: 本次写入时间。
            history_limit: 正常历史条数上限。
        Returns:
            已提交的运行与脱离数据库的历史候选。
        Raises:
            ConversationNotFound: 未知或他人的对话。
            DuplicateTurn: 请求标识已经使用。
            TurnConflict: 对话已占用或写入完整性冲突。
            ConversationStorageUnavailable: 存储失败，整笔回滚。
        """
        ...

    def finish_turn(
        self,
        turn_id: str,
        content: str,
        outcome: Outcome,
        now: datetime,
        citations: tuple[CitationSnapshot, ...] = (),
    ) -> MessageView:
        """原子保存唯一回复、更新终态并释放占用。

        Args:
            turn_id: 已提交的运行标识。
            content: 最终回复或保底文本。
            outcome: 完成、失败或中断状态。
            now: 终态写入时间。
        Returns:
            已提交的助手消息。
        Raises:
            TurnConflict: 运行不存在或已终结。
            ConversationStorageUnavailable: 存储失败。
        """
        ...

    def start_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """核对归属及运行状态后原子保存开始快照，失败不执行操作。"""
        ...

    def finish_operation(
        self, owner_id: str, conversation_id: str, turn_id: str, record: OperationRecord
    ) -> OperationRecord:
        """将仍运行的操作替换为完整终态，拒绝重复结束。"""
        ...

    def list_operations(
        self, owner_id: str, conversation_id: str, turn_id: str
    ) -> tuple[OperationRecord, ...]:
        """双层归属验证后读取序号顺序的快照。"""
        ...

    def list_conversations(self, owner_id: str, limit: int, offset: int) -> ConversationPage:
        """按归属和分页参数返回对话快照。

        Args:
            owner_id: 已验证账号。
            limit: 页大小。
            offset: 查询偏移。
        Returns:
            最近更新优先的对话页。
        Raises:
            ConversationStorageUnavailable: 存储读取失败。
        """
        ...

    def list_messages(
        self, owner_id: str, conversation_id: str, limit: int, before_id: int | None
    ) -> MessagePage:
        """按归属返回升序消息页；未知资源与他人资源使用同一错误。

        Args:
            owner_id: 已验证账号。
            conversation_id: 待查询对话。
            limit: 页大小。
            before_id: 更早消息游标，None 查询最新一页。
        Returns:
            升序消息页与下一页游标。
        Raises:
            ConversationNotFound: 对话不可见。
            ConversationStorageUnavailable: 存储读取失败。
        """
        ...

    def find_stale_turn_ids(self, owner_id: str, threshold: datetime) -> list[str]:
        """返回本账号在阈值之前仍运行的标识；不修改状态。

        Args:
            owner_id: 已验证账号。
            threshold: 残留运行截止时间。
        Returns:
            待恢复运行的标识列表。
        Raises:
            ConversationStorageUnavailable: 存储读取失败。
        """
        ...
