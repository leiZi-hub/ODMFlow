"""用途：本人售后异步查询适配；边界：模型不能传owner，SQL由业务包负责。"""

import asyncio

from odmflow.after_sales.application import AfterSalesReadService
from odmflow.after_sales.domain import AfterSalesList, AfterSalesLookup


class BoundAfterSalesGateway:
    """当前Session验证主体的只读端口。"""

    def __init__(self, service: AfterSalesReadService, owner_id: str) -> None:
        """可信调用方绑定本人身份，不进行数据库查询。"""
        self._service, self._owner = service, owner_id

    async def list(self) -> AfterSalesList:
        """线程池读取本人有界列表。"""
        return await asyncio.to_thread(self._service.list, self._owner)

    async def get(self, application_no: str) -> AfterSalesLookup:
        """按明确编号读取本人记录，越权查无。"""
        return await asyncio.to_thread(self._service.get, self._owner, application_no)
