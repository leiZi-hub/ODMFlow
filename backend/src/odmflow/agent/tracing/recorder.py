"""每轮操作保存门禁；负责序号与时钟，不执行工具或接触 ORM。"""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from odmflow.conversations import StartedTurn
from odmflow.conversations.operation_records import OperationRecord

from ..ports import AgentConversationPort
from .operations import OperationDescriptor, OperationDetails, OperationStatus
from .payloads import operation_payload


class PersistedOperationRecorder:
    """绑定可信用户与当前轮；保存失败直接传播，禁止后续执行。"""

    def __init__(self, conversations: AgentConversationPort, started: StartedTurn) -> None:
        """注入存储及可信轮快照；不从工具参数取账号。"""
        self._store, self._turn = conversations, started
        self._lock = asyncio.Lock()
        self._records: dict[str, tuple[OperationRecord, OperationDescriptor, float]] = {}

    async def start(
        self, descriptor: OperationDescriptor, details: OperationDetails
    ) -> OperationRecord:
        """提交开始快照后返回；入参为受信描述及受限明细。"""
        async with self._lock:
            record = OperationRecord(
                id=str(uuid4()),
                turn_id=self._turn.turn_id,
                sequence=len(self._records) + 1,
                status="running",
                started_at=datetime.now(UTC),
                payload_json=operation_payload(descriptor, details, OperationStatus.RUNNING),
            )
            saved = await self._store.start_operation(
                self._turn.owner_id, self._turn.conversation_id, self._turn.turn_id, record
            )
            self._records[saved.id] = (saved, descriptor, monotonic())
            return saved

    async def finish(
        self, operation_id: str, status: OperationStatus, details: OperationDetails
    ) -> OperationRecord:
        """原子保存完整终态；返回可安全发布的已保存快照。"""
        record, descriptor, clock = self._records[operation_id]
        finished = replace(
            record,
            status=status.value,
            finished_at=datetime.now(UTC),
            elapsed_ms=round((monotonic() - clock) * 1000),
            payload_json=operation_payload(descriptor, details, status),
        )
        return await self._store.finish_operation(
            self._turn.owner_id, self._turn.conversation_id, self._turn.turn_id, finished
        )
