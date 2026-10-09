"""画像SQL服务的线程池适配；每次调用拥有独立短事务，不跨模型等待持有Session。"""

from starlette.concurrency import run_in_threadpool

from odmflow.conversations.context_contracts import ContextRequest
from odmflow.profiles import ProfileCandidate, ProfileInputSnapshot, ProfileService, ProfileSnapshot


class ThreadedProfileGateway:
    """将同步画像公共服务适配为Agent所需的异步端口。"""

    def __init__(self, service: ProfileService) -> None:
        """注入公共服务；构造不访问数据库。"""
        self._service = service

    async def load_sources(self, request: ContextRequest, limit: int) -> ProfileInputSnapshot:
        """核验当前轮归属后返回画像与有界同会话用户来源。"""
        return await run_in_threadpool(self._service.load_sources, request, limit)

    async def apply_candidates(
        self,
        request: ContextRequest,
        snapshot: ProfileInputSnapshot,
        candidates: tuple[ProfileCandidate, ...],
    ) -> ProfileSnapshot:
        """在线程池等待来源/CAS事务成功，失败传播以供准备阶段降级。"""
        return await run_in_threadpool(
            self._service.apply_candidates, request, snapshot, candidates
        )
