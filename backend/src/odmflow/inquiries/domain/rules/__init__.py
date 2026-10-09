"""询盘领域规则公共入口。

用途：
    对领域层暴露缺失信息检查、冲突检查和需求状态评估接口。

边界：
    不暴露内部规则注册表，不调用外部服务，也不修改输入需求。
"""

from .assessment import assess_requirement, find_conflicts, find_missing_fields

__all__ = ["assess_requirement", "find_conflicts", "find_missing_fields"]
