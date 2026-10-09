"""用途：核验本轮引用并生成可持久化的回复来源。边界：不查询索引、不保存SQL、不信任模型自造来源。"""

from odmflow.conversations.operation_records import CitationSnapshot

from .tasks.contracts import TaskResult
from .tools.rag.evidence import PreparedKnowledge, resolve_citations


def build_partial_reply(results: tuple[TaskResult, ...], stop_reason: str) -> str:
    """确定性显示已核实有限结果；无可核实事实返回空，不把失败冒充成功。

    Args:
        results: 已完成真实操作记录的有限结果。
        stop_reason: 服务器停止分类；不包含SDK异常。
    Returns:
        模拟订单/进度/来源及未完成提示；无事实时返回空串。"""
    lines: list[str] = []
    statuses = {
        "pending_review": "待审核",
        "in_production": "生产中",
        "delivered": "已交付",
        "cancelled": "已取消",
    }
    for result in results:
        data = result.data
        if result.code == "awaiting_confirmation" and isinstance(data, dict):
            lines.append("模拟申请确认卡已准备，请核对卡片并点击确认；目前尚未提交申请。")
        elif result.code == "ok" and isinstance(data, dict) and data.get("simulated") is True:
            order = data.get("order")
            orders = [order] if isinstance(order, dict) else data.get("items", [])
            if isinstance(orders, list):
                for item in orders[:10]:
                    if isinstance(item, dict) and isinstance(item.get("order_no"), str):
                        status = statuses.get(str(item.get("status")), "状态待确认")
                        lines.append(f"模拟订单 {item['order_no']}：{status}。")
            if data.get("has_more"):
                lines.append("这里只展示最近部分记录，不是全部记录。")
            progress = data.get("progress")
            if isinstance(progress, list):
                for item in progress[:10]:
                    if isinstance(item, dict) and isinstance(item.get("description"), str):
                        lines.append(f"模拟进度：{item['description']}。")
        elif result.code == "empty":
            lines.append("本次查询未找到本人订单记录。")
        elif result.code == "not_found":
            lines.append("未找到本人可访问的该订单。")
        elif result.code == "ok" and result.sources:
            lines.append(
                "本轮已找到参考资料："
                + "、".join(f"[{source}]" for source in result.sources)
                + "。详细解读未完成，可继续询问。"
            )
        elif result.code == "ok" and isinstance(data, dict) and data.get("is_simulated") is True:
            lines.append("模拟需求评估已完成；请补充缺失字段并核实需求冲突，未创建订单。")
    if not lines:
        return ""
    return (
        "本轮部分处理未完成，以下为已核实结果：\n\n"
        + "\n".join(lines)
        + "\n\n其他内容尚未核实，请发送新的消息继续。"
    )


def prepare_reply(
    content: str, evidence: PreparedKnowledge | None
) -> tuple[str, tuple[CitationSnapshot, ...]]:
    """仅接受本轮实际注入的引用，归档对应原文快照。

    Args:
        content: 主模型最终回答。
        evidence: 本轮真实检索证据；无检索则为None。
    Returns:
        核验后的回答与来源快照。
    """
    content, cited = resolve_citations(content, evidence)
    citations = tuple(
        CitationSnapshot(
            source_id=item.source_id,
            chunk_id=item.chunk_id,
            doc_id=item.doc_id,
            title=item.title,
            section_path=item.section_path,
            version=item.version,
            source_path=item.source_path,
            text=item.text,
        )
        for item in cited
    )
    return content, citations
