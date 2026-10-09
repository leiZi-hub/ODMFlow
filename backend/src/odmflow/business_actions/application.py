"""用途：受控申请公共用例；边界：参数校验在此，事务细节在仓储，模型不能确认。"""

from datetime import datetime

from pydantic import JsonValue

from .domain import ActionPage, ActionView, AfterSalesApplication, OrderApplication
from .repository import SqlBusinessActionRepository


class BusinessActionService:
    """可信调用方提供身份与来源轮，所有写入受数据库门禁控制。"""

    def __init__(self, repository: SqlBusinessActionRepository, ttl_seconds: int = 1800) -> None:
        """注入仓储与预览有效期（秒），构造不连接数据库。"""
        self.repository = repository
        self.ttl_seconds = ttl_seconds

    def prepare(
        self,
        owner_id: str,
        conversation_id: str,
        turn_id: str,
        kind: str,
        parameters: dict[str, JsonValue],
    ) -> ActionView:
        """验证固定参数并保存预览；返回确认卡，不创建业务记录。"""
        if kind == "order_application":
            snapshot = OrderApplication.model_validate(parameters).model_dump_json()
        elif kind == "after_sales_application":
            snapshot = AfterSalesApplication.model_validate(parameters).model_dump_json()
        else:
            raise ValueError("unsupported_action_kind")
        return self.repository.prepare(
            owner_id, conversation_id, turn_id, kind, snapshot, self.ttl_seconds
        )

    def get(self, owner_id: str, action_id: str) -> ActionView:
        """获取本人权威快照；不存在或越权抛ActionNotFound。"""
        return self.repository.get(owner_id, action_id)

    def list(
        self, owner_id: str, conversation_id: str, limit: int = 10, offset: int = 0
    ) -> ActionPage:
        """查询本人指定对话的有界分页；不跨对话扩大范围。"""
        if not 1 <= limit <= 30 or offset < 0:
            raise ValueError("invalid_action_page")
        return self.repository.list(owner_id, conversation_id, limit, offset)

    def decide(self, owner_id: str, action_id: str, revision: int, confirmed: bool) -> ActionView:
        """短事务重验后执行一次；未知commit错误原样上抛，不谎报已回滚。"""
        return self.repository.decide(owner_id, action_id, revision, confirmed)

    def save_receipt(self, owner_id: str, action_id: str) -> None:
        """确认成功后幂等保存可见回执；错误由调用方单独处理。"""
        self.repository.save_receipt(owner_id, action_id)

    def terminal_before(self, cutoff: datetime) -> tuple[str, ...]:
        """维护端口只提供有限终态ID，用于本地图游标清理。"""
        return self.repository.terminal_before(cutoff)

    def mark_checkpoint_pruned(self, action_id: str) -> None:
        """维护端口记录终态清理进度；不更改业务状态。"""
        self.repository.mark_checkpoint_pruned(action_id)
