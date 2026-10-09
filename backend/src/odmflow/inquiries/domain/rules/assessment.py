"""询盘规则调度与状态评估。

用途：
    执行注册表中的全部缺失和冲突规则，并聚合最终需求评估状态。

边界：
    不定义具体业务规则、不访问外部服务，也不修改输入需求或规则注册表。
"""

from ..contracts import (
    AssessmentStatus,
    MissingField,
    RequirementAssessment,
    RequirementConflict,
    RequirementDraft,
)
from .registry import CONFLICT_RULES, MISSING_RULES


def find_missing_fields(requirement: RequirementDraft) -> tuple[MissingField, ...]:
    """执行全部缺失规则并按注册顺序返回结果。"""

    missing_fields: list[MissingField] = []
    for rule in MISSING_RULES:
        missing_fields.extend(rule(requirement))
    return tuple(missing_fields)


def find_conflicts(requirement: RequirementDraft) -> tuple[RequirementConflict, ...]:
    """执行全部冲突规则并按注册顺序返回结果。"""

    conflicts: list[RequirementConflict] = []
    for rule in CONFLICT_RULES:
        conflict = rule(requirement)
        if conflict is not None:
            conflicts.append(conflict)
    return tuple(conflicts)


def assess_requirement(requirement: RequirementDraft) -> RequirementAssessment:
    """汇总需求的缺失项、冲突和下一步评估状态。"""

    missing_fields = find_missing_fields(requirement)
    conflicts = find_conflicts(requirement)

    if conflicts:
        status = AssessmentStatus.HAS_CONFLICTS
    elif missing_fields:
        status = AssessmentStatus.NEEDS_CLARIFICATION
    else:
        status = AssessmentStatus.READY_FOR_REVIEW

    return RequirementAssessment(
        status=status,
        missing_fields=missing_fields,
        conflicts=conflicts,
        requirement=requirement,
    )
