"""用途：订单只读公共应用入口。边界：owner来自可信调用方，无订单写入流程。"""

from .domain import OrderList, OrderLookup, OrderStatus
from .repository import SqlOrderRepository


class OrderReadService:
    """共享安全查询用例，不依赖会话或Agent框架。"""

    def __init__(self, repository: SqlOrderRepository) -> None:
        """注入实际仓储，不执行查询。"""
        self.repository = repository

    def list_orders(self, owner_id: str, status: OrderStatus | None = None) -> OrderList:
        """查询本人有限订单列表；不扩大范围。

        Args:
            owner_id: 可信调用方已验证的登录用户标识。
            status: 可选状态过滤，无值则不限定状态。
        Returns:
            最多十条安全订单及是否还有更多。
        Raises:
            ValueError: 本人标识为空。
            OrderReadUnavailable: 仓储查询失败，附服务器分类结果。
        """
        if not owner_id:
            raise ValueError("owner_required")
        return self.repository.list_orders(owner_id, status)

    def get_order(self, owner_id: str, order_no: str) -> OrderLookup:
        """查询本人明确编号；不替用户猜最新订单。

        Args:
            owner_id: 服务端已验证的用户标识。
            order_no: 明确的业务订单号，不是用户身份。
        Returns:
            本人详情及有限进度；越权与不存在均为not_found。
        Raises:
            ValueError: 身份为空或订单号无效。
            OrderReadUnavailable: 仓储查询失败。
        """
        if not owner_id or not order_no.strip() or len(order_no.strip()) > 64:
            raise ValueError("invalid_order_target")
        return self.repository.get_order(owner_id, order_no.strip())
