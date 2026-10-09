"""用途：Session本人绑定的订单异步适配。边界：模型接口不能传owner，查询在线程池短Session内完成。"""

import asyncio

from odmflow.orders.application import OrderReadService
from odmflow.orders.domain import OrderList, OrderLookup, OrderStatus


class BoundOrderReadGateway:
    """一次运行的可信owner绑定，不暴露可覆盖的工具身份参数。"""

    def __init__(self, service: OrderReadService, owner_id: str) -> None:
        """仅由服务端验证Session后构造。"""
        self._service, self._owner_id = service, owner_id

    async def list_orders(self, status: OrderStatus | None = None) -> OrderList:
        """在线程池执行本人查询；取消不会启动重叠重试。

        Args:
            status: 可选业务状态，不含身份参数。
        Returns:
            绑定用户的有限订单列表。
        Raises:
            OrderReadUnavailable: 业务仓储转换的受控错误。
            asyncio.CancelledError: 调用方取消；底层线程可能仍在执行。
        """
        return await asyncio.to_thread(self._service.list_orders, self._owner_id, status)

    async def get_order(self, order_no: str) -> OrderLookup:
        """工具只提供业务目标，不改变本人归属。

        Args:
            order_no: 业务订单号。
        Returns:
            绑定用户可访问的详情或not_found。
        Raises:
            OrderReadUnavailable: 已结束查询的受控错误。
            asyncio.CancelledError: 上层取消，不代表线程已被杀死。
        """
        return await asyncio.to_thread(self._service.get_order, self._owner_id, order_no)
