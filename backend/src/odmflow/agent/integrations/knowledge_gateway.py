"""本地知识线程适配；限制每个进程一个实际检索，不把 CPU 工作放事件循环。"""

import asyncio

from odmflow.knowledge.application import KnowledgeService
from odmflow.knowledge.domain import KnowledgeError

from ..tools.rag.evidence import PreparedKnowledge, prepare_context


class ThreadedKnowledgeGateway:
    """一次注入已初始化服务；超时不取消实际线程，完成后才释放并发许可。"""

    def __init__(
        self,
        service: KnowledgeService,
        *,
        timeout: float = 5,
        max_chars: int = 6000,
        top_k: int = 3,
        max_distance: float | None = None,
    ) -> None:
        """注入查询预算，不触发模型下载或索引构建。"""
        self._service = service
        self._timeout, self._max_chars = timeout, max_chars
        self._top_k, self._max_distance = top_k, max_distance
        self._permit = asyncio.Semaphore(1)
        self._pending: set[asyncio.Task[PreparedKnowledge]] = set()

    async def validate_query(self, query: str) -> None:
        """先校验输入长度；仅分词，不编码。"""
        self._service.validate_query(query)

    async def retrieve(self, query: str) -> PreparedKnowledge:
        """限时等待许可与实际检索；返回送入模型的确切快照。"""
        async with asyncio.timeout(self._timeout):
            await self._permit.acquire()
            task = asyncio.create_task(asyncio.to_thread(self._retrieve, query))
            self._pending.add(task)
            task.add_done_callback(self._release)
            return await asyncio.shield(task)

    def _retrieve(self, query: str) -> PreparedKnowledge:
        """在线程内编码/检索/整理完整片段，不访问身份或业务数据库。"""
        try:
            result = self._service.search(query, self._top_k)
            return prepare_context(
                result, max_chars=self._max_chars, max_distance=self._max_distance
            )
        except KnowledgeError:
            raise
        except Exception as error:
            raise KnowledgeError("本地检索依赖失败") from error

    def _release(self, task: asyncio.Task[PreparedKnowledge]) -> None:
        """实际线程结束后释放许可，同时消费异常避免泄漏后台异常。"""
        self._pending.discard(task)
        self._permit.release()
        if not task.cancelled():
            task.exception()

    async def close(self) -> None:
        """生命周期结束时等待现存本地任务，不启动新请求。"""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)


class UnavailableKnowledgeGateway:
    """初始化失败的明确禁用适配，避免悄悄改成无知识企业答复。"""

    async def validate_query(self, query: str) -> None:
        """允许记录真实失败检索尝试，不泄露启动异常详情。"""

    async def retrieve(self, query: str) -> PreparedKnowledge:
        """始终显式失败，不请求模型。"""
        raise KnowledgeError("知识服务初始化失败")
