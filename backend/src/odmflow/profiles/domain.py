"""用途：定义用户画像允许字段、来源候选与快照。边界：不执行SQL/HTTP/模型，不存私人经历。"""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class ProfileField(StrEnum):
    """首版有真实消费方的稳定画像字段；不是任意用户资料字典。"""

    LANGUAGE = "language"
    RESPONSE_DETAIL = "response_detail"
    EXPLANATION_STYLE = "explanation_style"
    BUSINESS_ROLE = "business_role"
    PRODUCT_FOCUS = "product_focus"


FIELD_VALUES: dict[ProfileField, tuple[str, ...]] = {
    ProfileField.LANGUAGE: ("zh-CN", "en"),
    ProfileField.RESPONSE_DETAIL: ("brief", "balanced", "detailed"),
    ProfileField.EXPLANATION_STYLE: ("general", "java_comparison"),
}


class ProfileConflict(Exception):
    """画像版本已变化，调用方必须重读而非无声覆盖。"""


class ProfileUnavailable(Exception):
    """画像存储不可用；不向用户泄漏连接串/驱动错误。"""


class ProfileSourceInvalid(Exception):
    """画像来源未通过本人/原文/执行边界核验。"""


def reject_profile_credentials(value: str) -> None:
    """拒绝字段或证据中明显的凭证形式；不是完整隐私/秘密检测器。"""
    if re.search(
        r"sk-[a-zA-Z0-9_-]{12,}|password\s*[:=]|api[_ -]?key\s*[:=]|密码\s*[:：=]", value, re.I
    ):
        raise ValueError("画像及原话证据不能用于保存凭证")


def normalize_profile_value(field_key: str, value: str) -> str:
    """校验字段和值域，不把自由文本作为秘密存储入口。

    Args:
        field_key: 允许字段名。
        value: 待规范化的画像值。
    Returns:
        有界值。
    Raises:
        ValueError: 字段、长度、值域或明显秘密形式不合法。
    """
    key = ProfileField(field_key)
    result = value.strip()
    if not result or len(result) > 80 or any(ord(x) < 32 for x in result):
        raise ValueError("画像值必须为1–80个可见字符")
    if key in FIELD_VALUES and result not in FIELD_VALUES[key]:
        raise ValueError("画像值不在允许范围")
    reject_profile_credentials(result)
    return result


class ProfileCandidate(BaseModel):
    """模型提议的一个稳定字段及原文证据，不包含owner或写入权限。"""

    model_config = ConfigDict(extra="forbid", frozen=True)
    field_key: ProfileField
    value: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    source_message_id: int = Field(gt=0, strict=True)
    evidence: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)]

    @model_validator(mode="after")
    def validate_value(self) -> ProfileCandidate:
        """在模型/服务边界都校验值域，不接受未验证copy作为外部输入。"""
        normalize_profile_value(self.field_key, self.value)
        reject_profile_credentials(self.evidence)
        return self


@dataclass(frozen=True)
class ProfileItem:
    """一个有效或已抑制的画像字段；删除行不再注入模型。"""

    field_key: str
    value: str | None
    origin: str
    suppressed: bool
    source_conversation_id: str | None
    source_message_id: int | None
    evidence: str | None
    updated_at: datetime


@dataclass(frozen=True)
class ProfileSnapshot:
    """全用户版本和有界字段，支持并发更新而非重复存聊天。"""

    revision: int
    items: tuple[ProfileItem, ...]

    def active_values(self) -> tuple[tuple[str, str], ...]:
        """只返回可注入值，不暴露删除字段或原文证据。"""
        return tuple(
            (x.field_key, x.value) for x in self.items if x.value is not None and not x.suppressed
        )


@dataclass(frozen=True)
class ProfileSource:
    """SQL已验证的本人原始用户消息，绝不来自助手摘要。"""

    message_id: int
    content: str


@dataclass(frozen=True)
class ProfileInputSnapshot:
    """一次提取所用版本和限定会话原文；模型等待时不持SQL连接。"""

    profile: ProfileSnapshot
    sources: tuple[ProfileSource, ...]
