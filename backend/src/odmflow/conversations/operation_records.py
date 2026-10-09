"""用途：表达轮次操作/引用的通用持久快照与存储版本校验。

边界：不导入Agent枚举、LLM或ORM，不决定当前用户权限。
"""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type OperationState = Literal["running", "completed", "failed", "interrupted"]


@dataclass(frozen=True)
class CitationSnapshot:
    """最终回复引用的原文与来源；不依赖当前向量索引存活。"""

    source_id: str
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    version: str
    source_path: str
    text: str


@dataclass(frozen=True)
class OperationRecord:
    """单个操作的版本化JSON快照；描述字段留在payload，不重复建列。"""

    id: str
    turn_id: str
    sequence: int
    status: OperationState
    started_at: datetime
    payload_json: str
    finished_at: datetime | None = None
    elapsed_ms: int | None = None

    def payload(self) -> dict[str, JsonValue]:
        """校验存储边界的JSON版本及限额，不重新验证可信Agent内部枚举。

        Returns:
            已解析的通用字段。
        Raises:
            ValueError: 无效版本、JSON类型或超过128KiB。
        """
        if len(self.payload_json.encode()) > 128 * 1024:
            raise ValueError("操作快照超过128KiB")
        value = json.loads(self.payload_json)
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("操作快照版本无效")
        return cast(dict[str, JsonValue], value)
