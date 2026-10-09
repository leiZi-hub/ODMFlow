"""用途：有界增量摘要与覆盖编排；边界：通过端口保存，不依赖SQL/模型框架，不维护跨会话画像。"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from odmflow.conversations import ConversationStorageUnavailable, TurnConflict
from odmflow.conversations.context_contracts import ContextHistory, ContextMessage, ContextRequest

from ..contracts import ContextSummaryFailed
from ..ports import AgentContextPort
from .configuration import ContextSettings


def text_units(text: str) -> int:
    """使用UTF-8字节作为保守估算单位，不冒称未知供应商的精确token数。"""
    return len(text.encode("utf-8"))


@dataclass(frozen=True)
class PreparedContext:
    """已保存摘要、完整近期消息和可见降级说明，不包含全局可变状态。"""

    history: list[tuple[str, str]]
    summary: str = ""
    notice: str = ""
    batches: int = 0


def needs_summary(history: ContextHistory, settings: ContextSettings, message: str) -> bool:
    """根据未覆盖页、消息阈值和输入余量判断是否需要摘要调用。"""
    # 没有超出近期窗口的旧消息，就没有真实摘要任务；长首问交给总预算门禁。
    if not history.recent or not any(x.id < history.recent[0].id for x in history.pending):
        return False
    units = sum(text_units(x.content) + 128 for x in history.pending)
    units += text_units(history.summary.text) if history.summary else 0
    return (
        history.has_more
        or len(history.pending) > settings.trigger_messages
        or units + text_units(message) > settings.input_budget // 2
    )


async def prepare_context(
    history: ContextHistory,
    request: ContextRequest,
    store: AgentContextPort,
    summarize: Callable[[str, tuple[ContextMessage, ...]], Awaitable[str]],
    settings: ContextSettings,
    message: str,
    signature: str,
) -> PreparedContext:
    """合并旧摘要与尚未覆盖早期页，逐批保存后才推进游标。

    Args:
        history: 已授权的首个有界快照。
        request: 当前轮的可信边界。
        store: 异步短事务存储。
        summarize: 一次有界模型调用适配。
        settings: 最大批数、输入/输出和近期窗口限制。
        message: 当前用户消息，永不作为裁剪对象。
        signature: 当前模型/模板签名。
    Returns:
        可使用的摘要/近期消息；失败或积压明确标记降级。
    """
    batches = 0
    for _ in range(settings.max_batches):
        if not needs_summary(history, settings, message):
            break
        recent_start = history.recent[0].id if history.recent else request.before_message_id
        previous = history.summary.text if history.summary else ""
        remaining = settings.input_budget // 2 - text_units(previous) - 2048
        batch = []
        for item in history.pending:
            if item.id >= recent_start:
                break
            cost = text_units(item.content) + 256
            if cost > remaining:
                break
            batch.append(item)
            remaining -= cost
        if not batch:
            break
        try:
            text = await summarize(previous, tuple(batch))
            if not text.strip() or text_units(text) > settings.summary_tokens:
                raise ContextSummaryFailed
            await store.save(request, history, text, batch[-1].id, signature)
            batches += 1
            history = await store.load(
                request, settings.page_messages, settings.keep_messages, signature
            )
        except ContextSummaryFailed, TimeoutError, ConversationStorageUnavailable, TurnConflict:
            return PreparedContext(
                [(x.role, x.content) for x in history.recent],
                notice="较早内容暂未完整整理，本轮仅使用近期对话。\n\n",
                batches=batches,
            )
    limited = needs_summary(history, settings, message)
    rows = history.recent if limited else history.pending
    return PreparedContext(
        [(x.role, x.content) for x in rows],
        history.summary.text if history.summary else "",
        "较早内容尚未全部纳入，本轮使用已整理摘要与近期对话。\n\n" if limited else "",
        batches,
    )
