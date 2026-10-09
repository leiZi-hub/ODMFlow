"""用途：定义Agent回退历史的完整消息窗口。边界：不查询SQL、不生成摘要、不处理会话授权。"""

HISTORY_CANDIDATE_LIMIT = 20
HISTORY_MAX_CHARS = 12000


def clip_recent_history(history: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """在升序候选中保留连续完整近期消息；遇预算不足停止，不截断语义。

    Args:
        history: 仓储返回的升序完整normal消息，不含本轮新消息或fallback。
    Returns:
        升序的最多20条/12000字符完整近期历史。
    """
    result: list[tuple[str, str]] = []
    remaining = HISTORY_MAX_CHARS
    for role, content in reversed(history[-HISTORY_CANDIDATE_LIMIT:]):
        if len(content) > remaining:
            break
        result.append((role, content))
        remaining -= len(content)
    return list(reversed(result))
