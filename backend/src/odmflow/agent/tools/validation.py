"""用途：能力执行前检查参数。边界：不调用模型、不猜测身份或业务目标。"""

import re

from pydantic import BaseModel, ValidationError

from ..tasks.contracts import AgentTask, ArgumentIssue
from ..tasks.policy import has_identity_argument


class InvalidCapabilityArguments(ValueError):
    """只携带安全字段路径和错误类型，不携带用户原值。"""

    def __init__(self, issues: tuple[ArgumentIssue, ...]) -> None:
        """保存问题清单；身份或多余字段不能通过模型修补。"""
        super().__init__("invalid_arguments")
        self.issues = issues


def validate_arguments(task: AgentTask, schema: type[BaseModel]) -> BaseModel:
    """校验显式schema，返回规范化输入；无效参数不进入实际执行。"""
    arguments = task.arguments
    if has_identity_argument(arguments):
        raise InvalidCapabilityArguments((ArgumentIssue((), "identity_argument", False),))
    try:
        return schema.model_validate(arguments)
    except ValidationError as error:
        raise InvalidCapabilityArguments(
            tuple(
                ArgumentIssue(tuple(item["loc"]), item["type"], item["type"] != "extra_forbidden")
                for item in error.errors(include_input=False)
            )
        ) from None


def mentions_exact_order_number(number: str, messages: tuple[str, ...]) -> bool:
    """核对原话中的完整订单标识，不把相似前缀当作用户指定目标。

    Args:
        number: 已通过长度校验的订单号。
        messages: 可信用户原话，不包括模型自拟查询。
    Returns:
        任一原话出现完整订单号时为True；中文紧邻和标点不影响匹配。
    """
    pattern = re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(number) + r"(?![A-Za-z0-9_-])")
    return any(pattern.search(message) for message in messages)
