"""询盘字段冲突规则。

用途：
    为能够由结构化字段确定判断的业务冲突提供独立检查函数。

边界：
    不推断客户意图、认证义务或产品可生产性，也不决定最终评估状态。
"""

from ..contracts import AndroidDistribution, RequirementConflict, RequirementDraft


def check_gms_aosp_conflict(requirement: RequirementDraft) -> RequirementConflict | None:
    """检查 AOSP-only 与完整 Google Mobile Services 要求是否冲突。"""

    software = requirement.software
    if (
        software.android_distribution is AndroidDistribution.AOSP
        and software.google_mobile_services_required is True
    ):
        return RequirementConflict(
            code="GMS_AOSP_CONFLICT",
            field_paths=(
                "software.android_distribution",
                "software.google_mobile_services_required",
            ),
            reason="AOSP-only 与完整 Google Mobile Services 要求冲突",
        )

    return None


def check_gms_policy_conflict(requirement: RequirementDraft) -> RequirementConflict | None:
    """检查 GMS 发行方式与明确不需要 GMS 的声明是否冲突。"""

    software = requirement.software
    if (
        software.android_distribution is AndroidDistribution.GMS
        and software.google_mobile_services_required is False
    ):
        return RequirementConflict(
            code="GMS_POLICY_CONFLICT",
            field_paths=(
                "software.android_distribution",
                "software.google_mobile_services_required",
            ),
            reason="GMS 发行方式与明确不需要 Google Mobile Services 冲突",
        )

    return None


def check_deadline_order_conflict(requirement: RequirementDraft) -> RequirementConflict | None:
    """检查样机截止日期是否晚于量产截止日期。"""

    project = requirement.project
    if (
        project.sample_deadline is not None
        and project.mass_production_deadline is not None
        and project.sample_deadline > project.mass_production_deadline
    ):
        return RequirementConflict(
            code="DEADLINE_ORDER_CONFLICT",
            field_paths=(
                "project.sample_deadline",
                "project.mass_production_deadline",
            ),
            reason="样机截止日期不能晚于量产截止日期",
        )

    return None


def check_hardware_customization_conflict(
    requirement: RequirementDraft,
) -> RequirementConflict | None:
    """检查硬件定制开关与定制明细是否冲突。"""

    customization = requirement.customization
    if customization.hardware_customization is False and customization.hardware_customization_notes:
        return RequirementConflict(
            code="HARDWARE_CUSTOMIZATION_CONFLICT",
            field_paths=(
                "customization.hardware_customization",
                "customization.hardware_customization_notes",
            ),
            reason="声明不进行硬件定制，但同时填写了硬件定制明细",
        )

    return None
