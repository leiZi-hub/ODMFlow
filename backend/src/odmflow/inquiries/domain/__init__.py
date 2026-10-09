"""询盘领域层公开接口。

用途：
    集中导出调用方可以依赖的领域契约，隐藏内部文件组织方式。

边界：
    不实现领域规则、应用用例、HTTP 接口或基础设施适配。
"""

from .contracts import (
    AndroidDistribution,
    AssessmentStatus,
    ComplianceSpec,
    ConnectivityType,
    CustomizationSpec,
    HardwareSpec,
    MarketRegion,
    MissingField,
    PeripheralType,
    ProductType,
    ProjectSpec,
    RequirementAssessment,
    RequirementConflict,
    RequirementDraft,
    SoftwareSpec,
)
from .rules import assess_requirement, find_conflicts, find_missing_fields

__all__ = [
    "AndroidDistribution",
    "AssessmentStatus",
    "ComplianceSpec",
    "ConnectivityType",
    "CustomizationSpec",
    "HardwareSpec",
    "MarketRegion",
    "MissingField",
    "PeripheralType",
    "ProductType",
    "ProjectSpec",
    "RequirementAssessment",
    "RequirementConflict",
    "RequirementDraft",
    "SoftwareSpec",
    "assess_requirement",
    "find_conflicts",
    "find_missing_fields",
]
