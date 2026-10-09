"""确定性排名融合与精确内容去重；无SDK/模型依赖，不做语义重排。"""

from .domain import KnowledgeError, RouteContribution, SearchHit


def reciprocal_rank_fusion(
    routes: tuple[tuple[SearchHit, ...], ...], *, constant: int
) -> tuple[SearchHit, ...]:
    """按各路排名RRF合并同ID，保留原始评分。

    Args:
        routes: 有序候选路，每路同ID最多出现一次。
        constant: 正整数平滑常量；不是相似度阈值。
    Returns:
        融合分降序、同分按chunk_id排列的完整候选。
    Raises:
        KnowledgeError: 重复/来源错配或参数非法。
    """
    if not 1 <= constant <= 1000:
        raise KnowledgeError("RRF常量必须为1–1000")
    merged: dict[str, SearchHit] = {}
    for route in routes:
        seen: set[str] = set()
        for rank, hit in enumerate(route, 1):
            identity = hit.chunk.chunk_id
            if identity in seen:
                raise KnowledgeError("单路出现重复片段")
            seen.add(identity)
            previous = merged.get(identity)
            if previous is not None and previous.chunk != hit.chunk:
                raise KnowledgeError("融合候选来源错配")
            contributions = hit.contributions
            if not contributions and hit.distance is not None:
                contributions = (RouteContribution(route="vector", rank=rank, score=hit.distance),)
            if not contributions or len(contributions) != 1:
                raise KnowledgeError("召回路原始贡献缺失或重复")
            contribution = contributions[0]
            if contribution.rank != rank:
                raise KnowledgeError("召回路排名错配")
            old = previous.contributions if previous else ()
            if any(c.route == contribution.route for c in old):
                raise KnowledgeError("同一召回路重复贡献")
            merged[identity] = SearchHit(
                chunk=hit.chunk,
                distance=previous.distance
                if previous and previous.distance is not None
                else hit.distance,
                contributions=(*old, contribution),
                fusion_score=(previous.fusion_score or 0 if previous else 0)
                + 1 / (constant + rank),
            )
    return tuple(
        sorted(merged.values(), key=lambda hit: (-(hit.fusion_score or 0), hit.chunk.chunk_id))
    )


def unique_top_hits(hits: tuple[SearchHit, ...], top_k: int) -> tuple[SearchHit, ...]:
    """按content_hash精确去重后保留前K；不判断语义重复。

    Args:
        hits: 已排序候选。
        top_k: 最终预算。
    Returns:
        保持排序且内容不重复的候选子集。
    """
    seen: set[str] = set()
    selected: list[SearchHit] = []
    for hit in hits:
        if hit.chunk.content_hash not in seen:
            seen.add(hit.chunk.content_hash)
            selected.append(hit)
        if len(selected) == top_k:
            break
    return tuple(selected)
