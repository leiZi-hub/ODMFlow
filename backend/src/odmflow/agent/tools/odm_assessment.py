"""ODM 需求评估只读工具。

用途：把受限的模型工具参数转换为现有领域契约，并公开确定性评估结果。
边界：不访问数据库、创建草稿、推断真实产能或执行客户订单。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from odmflow.inquiries.domain import (
    AndroidDistribution,
    AssessmentStatus,
    ProductType,
    ProjectSpec,
    RequirementConflict,
    RequirementDraft,
    SoftwareSpec,
    assess_requirement,
)

from ..run_context import AgentRunContext
from ..tasks.contracts import AgentTask, TaskResult


class OdmAssessmentInput(BaseModel):
    """只接受首个 Agent 工具能够可靠抽取的合成 ODM 字段。"""

    model_config = ConfigDict(extra="forbid")

    product_type: ProductType | None = None
    quantity: Annotated[int, Field(gt=0)] | None = None
    android_distribution: AndroidDistribution | None = None
    google_mobile_services_required: bool | None = None


class OdmAssessmentResult(BaseModel):
    """只返回规则状态、待澄清字段和可核验冲突。"""

    status: AssessmentStatus
    missing_fields: tuple[str, ...]
    conflicts: tuple[RequirementConflict, ...]
    is_simulated: Literal[True] = True


def assess_odm_requirements(payload: OdmAssessmentInput) -> OdmAssessmentResult:
    """评估模型提供的有限字段，不改变领域规则或生成业务记录。

    Args:
        payload: 经 Pydantic 校验的合成 ODM 项目和软件字段。

    Returns:
        已登记领域规则的状态、缺失字段路径和冲突信息。
    """

    draft = RequirementDraft(
        project=ProjectSpec(product_type=payload.product_type, quantity=payload.quantity),
        software=SoftwareSpec(
            android_distribution=payload.android_distribution,
            google_mobile_services_required=payload.google_mobile_services_required,
        ),
    )
    assessment = assess_requirement(draft)
    return OdmAssessmentResult(
        status=assessment.status,
        missing_fields=tuple(item.field_path for item in assessment.missing_fields),
        conflicts=assessment.conflicts,
    )


async def execute_assessment(task: AgentTask, context: AgentRunContext) -> TaskResult:
    """直接执行受限字段的确定性规则，不造框架ToolRuntime。"""
    result = assess_odm_requirements(OdmAssessmentInput.model_validate(task.arguments))
    return TaskResult(task.task_id, "ok", result.model_dump(mode="json"))
