"""询盘规则注册表。

用途：
    显式登记缺失信息规则和冲突规则，并固定可审阅的执行顺序。

边界：
    不执行规则、不修改注册表，也不通过自动扫描或装饰器产生导入副作用。
"""

from collections.abc import Callable

from ..contracts import MissingField, RequirementConflict, RequirementDraft
from .conflicts import (
    check_deadline_order_conflict,
    check_gms_aosp_conflict,
    check_gms_policy_conflict,
    check_hardware_customization_conflict,
)
from .missing import (
    check_base_fields,
    check_compliance_fields,
    check_connectivity_fields,
    check_product_hardware_fields,
)

type MissingRule = Callable[[RequirementDraft], tuple[MissingField, ...]]
type ConflictRule = Callable[[RequirementDraft], RequirementConflict | None]

MISSING_RULES: tuple[MissingRule, ...] = (
    check_base_fields,
    check_product_hardware_fields,
    check_connectivity_fields,
    check_compliance_fields,
)

CONFLICT_RULES: tuple[ConflictRule, ...] = (
    check_gms_aosp_conflict,
    check_gms_policy_conflict,
    check_deadline_order_conflict,
    check_hardware_customization_conflict,
)
