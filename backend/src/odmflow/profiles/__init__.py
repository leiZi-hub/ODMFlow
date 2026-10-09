"""用途：导出画像应用与稳定契约。边界：不导出SQL适配、不注册工具或执行外部操作。"""

from .application import ProfileService
from .domain import (
    ProfileCandidate,
    ProfileConflict,
    ProfileInputSnapshot,
    ProfileSnapshot,
    ProfileSourceInvalid,
    ProfileUnavailable,
)

__all__ = [
    "ProfileService",
    "ProfileCandidate",
    "ProfileConflict",
    "ProfileInputSnapshot",
    "ProfileSnapshot",
    "ProfileSourceInvalid",
    "ProfileUnavailable",
]
