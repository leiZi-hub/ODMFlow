"""用途：本人售后公共读入口；边界：不接受调用方扩大权限或写入。"""

from .domain import AfterSalesList, AfterSalesLookup
from .repository import SqlAfterSalesRepository


class AfterSalesReadService:
    """薄应用用例，SQL保留在仓储。"""

    def __init__(self, repository: SqlAfterSalesRepository) -> None:
        """注入真实仓储，不进行查询。"""
        self.repository = repository

    def list(self, owner_id: str) -> AfterSalesList:
        """查询当前登录用户的有界受理记录；空身份拒绝。"""
        if not owner_id:
            raise ValueError("owner_required")
        return self.repository.list(owner_id)

    def get(self, owner_id: str, application_no: str) -> AfterSalesLookup:
        """查询本人明确编号；不猜最新申请。"""
        if not owner_id or not application_no or len(application_no) > 64:
            raise ValueError("invalid_application_target")
        return self.repository.get(owner_id, application_no)
