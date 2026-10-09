"""用途：摘要存储线程池适配；边界：不等待模型、不将Session带到异步任务、不读取环境密钥。"""

from starlette.concurrency import run_in_threadpool

from odmflow.conversations.context_contracts import (
    ContextHistory,
    ContextRequest,
    ConversationSummarySnapshot,
)
from odmflow.conversations.context_repository import SqlConversationContextRepository


class ThreadedContextGateway:
    """把完整摘要短事务放到线程池，模型等待不占用数据库连接。"""

    def __init__(self, repository: SqlConversationContextRepository) -> None:
        """注入专用摘要仓储；不连接数据库。"""
        self._repository = repository

    async def load(
        self, request: ContextRequest, limit: int, keep: int, signature: str
    ) -> ContextHistory:
        """等待有界原文与有效摘要快照；参数/异常同SQL仓储。"""
        return await run_in_threadpool(self._repository.load, request, limit, keep, signature)

    async def save(
        self,
        request: ContextRequest,
        history: ContextHistory,
        text: str,
        through_id: int,
        signature: str,
    ) -> ConversationSummarySnapshot:
        """等待CAS保存后才返回可用于模型的版本；不跨异步任务持Session。"""
        return await run_in_threadpool(
            self._repository.save, request, history, text, through_id, signature
        )
