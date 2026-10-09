"""用途：将服务端身份和来源轮绑定申请端口；边界：工具只能提供业务参数。"""

from pydantic import JsonValue

from odmflow.business_actions.domain import ActionView

from ..approvals.service import ApprovalService


class BoundActionGateway:
    """每轮独立绑定，不允许模型修改owner/conversation/turn。"""

    def __init__(
        self, service: ApprovalService, owner_id: str, conversation_id: str, turn_id: str
    ) -> None:
        """仅组合根/应用用例使用已校验来源构造。"""
        self._service, self._owner = service, owner_id
        self._conversation, self._turn = conversation_id, turn_id

    async def prepare(self, kind: str, parameters: dict[str, JsonValue]) -> ActionView:
        """仅准备确认卡；不提供confirm/execute方法。"""
        return await self._service.prepare(
            self._owner, self._conversation, self._turn, kind, parameters
        )
