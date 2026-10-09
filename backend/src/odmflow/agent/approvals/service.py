"""用途：暂停、恢复与文件生命周期；边界：不放SQL、模型预算或HTTP授权。"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command, StateSnapshot
from pydantic import JsonValue

from odmflow.business_actions.application import BusinessActionService
from odmflow.business_actions.domain import ActionConflict, ActionNotFound, ActionPage, ActionView

from .graph import TrustedApprovalContext, build_approval_graph

logger = logging.getLogger(__name__)


class ApprovalUnavailable(Exception):
    """断点不可恢复或执行结果暂时不明；不能因此声称业务回滚。"""


def _config(action_id: str) -> RunnableConfig:
    """服务器派生唯一写图ID，客户端与模型不能指定thread_id。"""
    return {"configurable": {"thread_id": "approval:" + action_id}, "recursion_limit": 8}


class ApprovalService:
    """本地串行写图 + 数据库事务双重保护；重建实例不丢待确认动作。"""

    def __init__(
        self,
        business: BusinessActionService,
        path: Path,
        resume_timeout_seconds: float = 30,
        terminal_retention_days: int = 7,
    ) -> None:
        """保存可信业务端口、文件位置和恢复限时；构造不建立连接。"""
        self.business = business
        self.path = path.resolve()
        self.timeout = resume_timeout_seconds
        self.retention_days = terminal_retention_days
        self._last_cleanup = float("-inf")
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def _saver(self) -> AsyncIterator[AsyncSqliteSaver]:
        """每次有限调用打开并关闭文件；严格反序列化，不允许动态pickle。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(str(self.path)) as connection:
            serializer = JsonPlusSerializer(
                pickle_fallback=False, allowed_json_modules=[], allowed_msgpack_modules=[]
            )
            saver = AsyncSqliteSaver(connection, serde=serializer)
            yield saver

    async def prepare(
        self,
        owner_id: str,
        conversation_id: str,
        turn_id: str,
        kind: str,
        parameters: dict[str, JsonValue],
    ) -> ActionView:
        """保存幂等预览后跑到原生interrupt；不给模型提供确认函数。"""
        if self.path.exists() and monotonic() - self._last_cleanup > 3600:
            try:
                await self.cleanup(self.retention_days)
            except Exception as error:
                logger.warning("Approval checkpoint cleanup unavailable: %s", type(error).__name__)
            self._last_cleanup = monotonic()
        async with self._lock:
            action = await asyncio.to_thread(
                self.business.prepare, owner_id, conversation_id, turn_id, kind, parameters
            )
            async with self._saver() as saver:
                graph = build_approval_graph(saver)
                config = _config(action.id)
                snapshot = await graph.aget_state(config)
                if not snapshot.values and action.status == "pending_confirmation":
                    await graph.ainvoke(
                        {"action_id": action.id, "revision": action.revision},
                        config,
                        context=TrustedApprovalContext(owner_id, self.business),
                    )
            return action

    async def decide(
        self, owner_id: str, action_id: str, revision: int, confirmed: bool
    ) -> ActionView:
        """重新绑定Session身份；成功业务优先，未知断点不盲写。"""
        async with self._lock:
            action = await asyncio.to_thread(self.business.get, owner_id, action_id)
            if action.revision != revision:
                raise ActionConflict("revision_changed")
            if action.status != "pending_confirmation":
                actual = await asyncio.to_thread(
                    self.business.decide, owner_id, action_id, revision, confirmed
                )
                await self._receipt(owner_id, action_id)
                return actual
            try:
                async with self._saver() as saver:
                    graph = build_approval_graph(saver)
                    config = _config(action_id)
                    snapshot = await graph.aget_state(config)
                    if not snapshot.values or not snapshot.next:
                        raise ApprovalUnavailable("checkpoint_missing")
                    if (
                        snapshot.values.get("action_id") != action_id
                        or snapshot.values.get("revision") != revision
                    ):
                        raise ApprovalUnavailable("checkpoint_mismatch")
                    async with asyncio.timeout(self.timeout):
                        await graph.ainvoke(
                            Command(resume=confirmed),
                            config,
                            context=TrustedApprovalContext(owner_id, self.business),
                        )
            except ActionNotFound, ActionConflict:
                raise
            except Exception as error:
                # checkpoint写失败可能发生在MySQL已commit之后；先读业务，禁止自动再写。
                actual = await asyncio.to_thread(self.business.get, owner_id, action_id)
                if actual.status != "pending_confirmation":
                    await self._receipt(owner_id, action_id)
                    return actual
                raise ApprovalUnavailable("approval_result_unknown") from error
            actual = await asyncio.to_thread(self.business.get, owner_id, action_id)
            await self._receipt(owner_id, action_id)
            return actual

    async def _receipt(self, owner_id: str, action_id: str) -> None:
        """回执写失败只记录分类，确认卡权威结果仍可GET，重复确认可补投影。"""
        try:
            await asyncio.to_thread(self.business.save_receipt, owner_id, action_id)
        except Exception as error:
            logger.warning("Approval receipt unavailable: %s", type(error).__name__)

    async def get(self, owner_id: str, action_id: str) -> ActionView:
        """读取本人权威状态，不依赖checkpoint可用性。"""
        return await asyncio.to_thread(self.business.get, owner_id, action_id)

    async def list(
        self, owner_id: str, conversation_id: str, limit: int = 10, offset: int = 0
    ) -> ActionPage:
        """读取本人确认卡分页，身份与对话同时核验。"""
        return await asyncio.to_thread(self.business.list, owner_id, conversation_id, limit, offset)

    async def inspect(self, action_id: str) -> StateSnapshot:
        """仅内部测试/维护读取游标；没有HTTP或模型调用入口。"""
        async with self._saver() as saver:
            return await build_approval_graph(saver).aget_state(_config(action_id))

    async def close(self) -> None:
        """等当前受控操作退出；每个文件连接由_saver上下文自动释放。"""
        async with self._lock:
            pass

    async def cleanup(self, retention_days: int) -> int:
        """最多清理100个超期终态图游标；MySQL业务/审计和pending图一律保留。"""
        if not 1 <= retention_days <= 90:
            raise ValueError("invalid_retention")
        async with self._lock:
            ids = await asyncio.to_thread(
                self.business.terminal_before, datetime.now(UTC) - timedelta(days=retention_days)
            )
            if not ids or not self.path.exists():
                return 0
            removed = 0
            async with self._saver() as saver:
                for action_id in ids:
                    if await saver.aget_tuple(_config(action_id)) is not None:
                        await saver.adelete_thread("approval:" + action_id)
                        removed += 1
                    await asyncio.to_thread(self.business.mark_checkpoint_pruned, action_id)
            return removed
