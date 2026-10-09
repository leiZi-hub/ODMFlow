"""用途：分类策略的不可变快照与严格校验；边界：无文件、环境、框架或业务IO。"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from types import UnionType
from typing import Literal, get_args, get_origin, get_type_hints


class ConfigurationError(ValueError):
    """可安全展示的配置诊断；不携带原始值、秘密或底层异常正文。"""


@dataclass(frozen=True)
class ModelSettings:
    """模型请求等待策略；不保存服务商地址或密钥。"""

    request_timeout_seconds: float = 120


@dataclass(frozen=True)
class TaskPolicy:
    """显式任务图预算；只允许收紧代码硬上限。"""

    max_tasks: int = 4
    max_capability_calls: int = 4
    max_model_calls: int = 4
    max_replans: int = 1
    max_argument_repairs: int = 1


@dataclass(frozen=True)
class AgentSettings:
    """整轮硬截止与任务策略；不负责模型执行。"""

    turn_timeout_seconds: float = 300
    tasks: TaskPolicy = field(default_factory=TaskPolicy)


@dataclass(frozen=True)
class RagSettings:
    """在线启用、共享召回策略及注入预算；资源位置仍由环境决定。"""

    enabled: bool = False
    retrieval_mode: Literal["vector", "bm25", "hybrid"] = "vector"
    candidate_k: int = 10
    top_k: int = 3
    rrf_constant: int = 60
    timeout_seconds: float = 5
    max_context_chars: int = 6000
    max_distance: float | None = None


@dataclass(frozen=True)
class ConversationMemorySettings:
    """同会话摘要与输入预算；消息条数不是对话轮数。"""

    enabled: bool = True
    window_tokens: int = 16384
    output_tokens: int = 2048
    keep_messages: int = 12
    trigger_messages: int = 24
    summary_tokens: int = 1024
    summary_timeout_seconds: float = 30
    max_batches: int = 2
    page_messages: int = 64


@dataclass(frozen=True)
class ProfilePolicy:
    """结构化本人画像准备策略；不负责人工管理接口。"""

    enabled: bool = True
    timeout_seconds: float = 10


@dataclass(frozen=True)
class MemorySettings:
    """会话/本人画像策略分组；不存放真实记忆。"""

    conversation: ConversationMemorySettings = field(default_factory=ConversationMemorySettings)
    profile: ProfilePolicy = field(default_factory=ProfilePolicy)


@dataclass(frozen=True)
class OrderReadSettings:
    """服务器分类的有限只读重试开关；不扩大权限或次数。"""

    retry_enabled: bool = True


@dataclass(frozen=True)
class OrderSettings:
    """订单读策略；当前不配置写操作。"""

    read: OrderReadSettings = field(default_factory=OrderReadSettings)


@dataclass(frozen=True)
class ApprovalSettings:
    """本地确认图策略；真实密钥/连接仍由.env提供。"""

    enabled: bool = True
    checkpoint_path: str = "data/private/agent-checkpoints.sqlite"
    ttl_seconds: int = 1800
    resume_timeout_seconds: float = 30
    terminal_retention_days: int = 7


@dataclass(frozen=True)
class ApplicationSettings:
    """启动时校验的完整快照；通过注入共享，不每轮读文件。"""

    model: ModelSettings = field(default_factory=ModelSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    rag: RagSettings = field(default_factory=RagSettings)
    memory: MemorySettings = field(default_factory=MemorySettings)
    orders: OrderSettings = field(default_factory=OrderSettings)
    approvals: ApprovalSettings = field(default_factory=ApprovalSettings)

    def __post_init__(self) -> None:
        """类型、有限预算与跨组约束门禁；直接构造也不绕过。"""
        _validate_types(self, "")
        if not self.approvals.checkpoint_path.strip():
            raise ConfigurationError("approvals.checkpoint_path 不得为空")
        _range(self.approvals.ttl_seconds, 60, 86400, "approvals.ttl_seconds")
        _range(self.approvals.resume_timeout_seconds, 1, 120, "approvals.resume_timeout_seconds")
        _range(self.approvals.terminal_retention_days, 1, 90, "approvals.terminal_retention_days")
        _positive(self.model.request_timeout_seconds, "model.request_timeout_seconds")
        _positive(self.agent.turn_timeout_seconds, "agent.turn_timeout_seconds")
        if self.agent.turn_timeout_seconds < self.model.request_timeout_seconds:
            raise ConfigurationError(
                "agent.turn_timeout_seconds 必须不小于 model.request_timeout_seconds"
            )
        for name, minimum, maximum in (
            ("max_tasks", 1, 4),
            ("max_capability_calls", 1, 4),
            ("max_model_calls", 2, 4),
            ("max_replans", 0, 1),
            ("max_argument_repairs", 0, 1),
        ):
            _range(getattr(self.agent.tasks, name), minimum, maximum, "agent.tasks." + name)
        _range(self.rag.top_k, 1, 3, "rag.top_k")
        _range(self.rag.candidate_k, self.rag.top_k, 20, "rag.candidate_k")
        _range(self.rag.rrf_constant, 1, 1000, "rag.rrf_constant")
        _range(self.rag.max_context_chars, 1, 24000, "rag.max_context_chars")
        _positive(self.rag.timeout_seconds, "rag.timeout_seconds")
        if self.rag.max_distance is not None:
            if self.rag.retrieval_mode != "vector" or self.rag.max_distance < 0:
                raise ConfigurationError("rag.max_distance 仅可为 vector 模式的有限非负阈值")
        context = self.memory.conversation
        _range(context.window_tokens, 4096, 1000000, "memory.conversation.window_tokens")
        _range(
            context.output_tokens,
            256,
            context.window_tokens - 1025,
            "memory.conversation.output_tokens",
        )
        _range(context.trigger_messages, 2, 64, "memory.conversation.trigger_messages")
        _range(
            context.keep_messages,
            1,
            context.trigger_messages - 1,
            "memory.conversation.keep_messages",
        )
        _range(context.summary_tokens, 128, 2048, "memory.conversation.summary_tokens")
        if context.summary_tokens >= (context.window_tokens - context.output_tokens) // 2:
            raise ConfigurationError("memory.conversation.summary_tokens 必须小于输入预算一半")
        _positive(context.summary_timeout_seconds, "memory.conversation.summary_timeout_seconds")
        _range(
            context.summary_timeout_seconds, 0, 120, "memory.conversation.summary_timeout_seconds"
        )
        _range(context.max_batches, 1, 4, "memory.conversation.max_batches")
        _range(
            context.page_messages,
            context.trigger_messages,
            128,
            "memory.conversation.page_messages",
        )
        _positive(self.memory.profile.timeout_seconds, "memory.profile.timeout_seconds")
        _range(self.memory.profile.timeout_seconds, 0, 60, "memory.profile.timeout_seconds")


def _range(value: float, minimum: float, maximum: float, path: str) -> None:
    if not minimum <= value <= maximum:
        raise ConfigurationError(f"{path} 超出允许范围")


def _positive(value: float, path: str) -> None:
    if value <= 0:
        raise ConfigurationError(f"{path} 必须是有限正数")


def _matches(value: object, annotation: object) -> bool:
    """仅允许契约的原生类型；特别排除 bool 冒充整数。"""
    if get_origin(annotation) is UnionType:
        return any(_matches(value, member) for member in get_args(annotation))
    if get_origin(annotation) is Literal:
        return type(value) is str and value in get_args(annotation)
    if annotation is float:
        if type(value) not in {int, float}:
            return False
        try:
            return math.isfinite(value)  # type: ignore[arg-type]
        except OverflowError:
            return False
    if annotation is type(None):
        return value is None
    return type(value) is annotation


def _validate_types(group: object, prefix: str) -> None:
    hints = get_type_hints(type(group))
    for item in fields(group):  # type: ignore[arg-type]
        path = f"{prefix}.{item.name}" if prefix else item.name
        value = getattr(group, item.name)
        if not _matches(value, hints[item.name]):
            raise ConfigurationError(f"{path} 类型或有限数值无效")
        if is_dataclass(value):
            _validate_types(value, path)


def _build[T](model: type[T], document: Mapping[str, object], prefix: str) -> T:
    defaults = model()
    declared = {item.name for item in fields(defaults)}  # type: ignore[arg-type]
    if set(document) - declared:
        raise ConfigurationError(f"{prefix or 'application'} 包含未知配置项")
    hints = get_type_hints(model)
    values: dict[str, object] = {}
    for name, value in document.items():
        path = f"{prefix}.{name}" if prefix else name
        annotation = hints[name]
        if isinstance(annotation, type) and is_dataclass(annotation):
            if not isinstance(value, Mapping):
                raise ConfigurationError(f"{path} 必须是分类表")
            values[name] = _build(annotation, value, path)
        else:
            if not _matches(value, annotation):
                raise ConfigurationError(f"{path} 类型或有限数值无效")
            values[name] = value
    return model(**values)


def parse_application_settings(document: Mapping[str, object]) -> ApplicationSettings:
    """严格构造完整策略快照。

    Args:
        document: TOML解析的分类映射；未填写已知项沿用安全默认。
    Returns:
        不可变且通过预算校验的快照。
    Raises:
        ConfigurationError: 未知项、类型或范围/跨字段组合非法。
    """
    return _build(ApplicationSettings, document, "")
