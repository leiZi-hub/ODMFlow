"""用途：组装本地受控写图；边界：构造不读库、不自动迁移或创建断点文件。"""

from sqlalchemy.orm import Session, sessionmaker

from odmflow.business_actions.application import BusinessActionService
from odmflow.business_actions.repository import SqlBusinessActionRepository
from odmflow.configuration.loader import resolve_project_resource_path
from odmflow.configuration.models import ApprovalSettings

from .service import ApprovalService


def build_approval_service(
    sessions: sessionmaker[Session] | None, policy: ApprovalSettings
) -> ApprovalService | None:
    """由组合根使用已加载策略构造；缺数据库或显式禁用时不开放准备能力。"""
    if sessions is None or not policy.enabled:
        return None
    business = BusinessActionService(SqlBusinessActionRepository(sessions), policy.ttl_seconds)
    return ApprovalService(
        business,
        resolve_project_resource_path(policy.checkpoint_path),
        policy.resume_timeout_seconds,
        policy.terminal_retention_days,
    )
