"""用途：登记旧策略变量及迁移目标；边界：不读取旧值、不做兼容覆盖。"""

from collections.abc import Mapping
from types import MappingProxyType

from .models import ConfigurationError

LEGACY_POLICY_KEYS = MappingProxyType(
    {
        "ODMFLOW_LLM_TIMEOUT_SECONDS": "model.request_timeout_seconds",
        "ODMFLOW_AGENT_TIMEOUT_SECONDS": "agent.turn_timeout_seconds",
        "ODMFLOW_TASK_MAX_TASKS": "agent.tasks.max_tasks",
        "ODMFLOW_TASK_MAX_CAPABILITY_CALLS": "agent.tasks.max_capability_calls",
        "ODMFLOW_TASK_MAX_MODEL_CALLS": "agent.tasks.max_model_calls",
        "ODMFLOW_TASK_MAX_REPLANS": "agent.tasks.max_replans",
        "ODMFLOW_TASK_MAX_ARGUMENT_REPAIRS": "agent.tasks.max_argument_repairs",
        "ODMFLOW_RAG_ENABLED": "rag.enabled",
        "ODMFLOW_RAG_RETRIEVAL_MODE": "rag.retrieval_mode",
        "ODMFLOW_RAG_CANDIDATE_K": "rag.candidate_k",
        "ODMFLOW_RAG_TOP_K": "rag.top_k",
        "ODMFLOW_RAG_RRF_CONSTANT": "rag.rrf_constant",
        "ODMFLOW_RAG_TIMEOUT_SECONDS": "rag.timeout_seconds",
        "ODMFLOW_RAG_MAX_CONTEXT_CHARS": "rag.max_context_chars",
        "ODMFLOW_RAG_MAX_DISTANCE": "rag.max_distance",
        "ODMFLOW_CONTEXT_ENABLED": "memory.conversation.enabled",
        "ODMFLOW_CONTEXT_WINDOW_TOKENS": "memory.conversation.window_tokens",
        "ODMFLOW_CONTEXT_OUTPUT_TOKENS": "memory.conversation.output_tokens",
        "ODMFLOW_CONTEXT_KEEP_MESSAGES": "memory.conversation.keep_messages",
        "ODMFLOW_CONTEXT_TRIGGER_MESSAGES": "memory.conversation.trigger_messages",
        "ODMFLOW_CONTEXT_SUMMARY_TOKENS": "memory.conversation.summary_tokens",
        "ODMFLOW_CONTEXT_SUMMARY_TIMEOUT_SECONDS": "memory.conversation.summary_timeout_seconds",
        "ODMFLOW_CONTEXT_MAX_BATCHES": "memory.conversation.max_batches",
        "ODMFLOW_CONTEXT_PAGE_MESSAGES": "memory.conversation.page_messages",
        "ODMFLOW_PROFILE_ENABLED": "memory.profile.enabled",
        "ODMFLOW_PROFILE_TIMEOUT_SECONDS": "memory.profile.timeout_seconds",
        "ODMFLOW_ORDER_READ_RETRY_ENABLED": "orders.read.retry_enabled",
    }
)


def reject_legacy_policy_variables(environment: Mapping[str, str]) -> None:
    """拒绝旧项，避免忽略用户已调整的值。

    Args:
        environment: 环境映射，仅检查登记键是否存在。
    Raises:
        ConfigurationError: 需要先迁移到实际TOML；不返回旧值。
    """
    found = [
        f"{key} → {target}" for key, target in LEGACY_POLICY_KEYS.items() if key in environment
    ]
    if found:
        raise ConfigurationError(
            "请先将以下旧环境策略迁移到应用配置并移除旧变量：" + "；".join(found)
        )
