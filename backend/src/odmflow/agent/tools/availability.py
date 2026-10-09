"""用途：统一按本轮可信端口过滤能力；边界：不以意图或提示授予权限。"""

from ..run_context import AgentRunContext
from ..tasks.contracts import Capability
from ..tasks.policy import WRITE_PREVIEWS


def capability_available(capability: Capability, context: AgentRunContext) -> bool:
    """仅已绑定对应本人端口才向模型提供私有能力。"""
    if capability in WRITE_PREVIEWS:
        return context.actions is not None
    if capability in {Capability.LIST_MY_AFTER_SALES, Capability.GET_MY_AFTER_SALES}:
        return context.after_sales is not None
    if capability in {Capability.LIST_MY_ORDERS, Capability.GET_MY_ORDER}:
        return context.orders is not None
    return True
