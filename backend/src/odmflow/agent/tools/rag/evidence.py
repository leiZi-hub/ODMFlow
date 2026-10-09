"""用途：筛选检索证据、构造实际注入文本并核验引用。

边界：只处理不可变来源，不调用LLM、数据库或HTTP，不推断意图。
"""

import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from odmflow.knowledge.domain import (
    IndexManifest,
    KnowledgeChunk,
    KnowledgeError,
    RetrievalMode,
    RouteContribution,
    SearchResult,
)


class KnowledgeSource(KnowledgeChunk):
    """本轮选用的原文快照及可信引用编号；不是模型声明的来源。"""

    source_id: str


class CandidateEvidence(BaseModel):
    """一个候选的原排名、距离及选择理由；不把距离解释为概率。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    rank: int
    chunk: KnowledgeChunk
    distance: float | None
    reason: Literal["selected", "duplicate", "context_budget", "distance", "rank_budget"]
    source_id: str | None = None
    contributions: tuple[RouteContribution, ...] = ()
    fusion_score: float | None = None


class PreparedKnowledge(BaseModel):
    """候选、实际选用和注入文本；不代表模型最终引用了所有选用证据。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    query: str
    manifest: IndexManifest
    candidates: tuple[CandidateEvidence, ...]
    sources: tuple[KnowledgeSource, ...]
    injected_context: str
    distance_filter: Literal["enabled", "disabled"]
    retrieval_mode: RetrievalMode = "vector"
    retrieval_signature: str = "vector-cosine-v1"
    route_timings_ms: dict[str, float] = Field(default_factory=dict)


def prepare_context(
    result: SearchResult, *, max_chars: int, max_distance: float | None
) -> PreparedKnowledge:
    """按真实排序去重和筛选整片段，保存完全相同的实际注入文本。

    Args:
        result: 含索引版本的向量近邻。
        max_chars: 上下文完整字符预算，不是Embedding token上限。
        max_distance: 经独立评估后配置的距离边界，None表示未启用。
    Returns:
        不可变的候选、选用来源与注入内容。
    Raises:
        KnowledgeError: 预算或距离非法。
    """
    if max_chars <= 0 or (
        max_distance is not None and (not math.isfinite(max_distance) or max_distance < 0)
    ):
        raise KnowledgeError("上下文预算或距离边界无效")
    if max_distance is not None and result.retrieval_mode != "vector":
        raise KnowledgeError("距离阈值仅支持向量模式")
    candidates: list[CandidateEvidence] = []
    sources: list[KnowledgeSource] = []
    sections: list[str] = []
    seen: set[str] = set()
    selected_ids = {hit.chunk.chunk_id for hit in result.hits}
    ranked = result.candidates or result.hits
    for rank, hit in enumerate(ranked, 1):
        if hit.distance is not None and not math.isfinite(hit.distance):
            raise KnowledgeError("候选距离无效")
        if result.retrieval_mode == "vector" and hit.distance is None:
            raise KnowledgeError("向量候选缺少距离")
        reason: Literal["selected", "duplicate", "context_budget", "distance", "rank_budget"] = (
            "selected"
        )
        source_id: str | None = None
        label = f"K{len(sources) + 1}"
        block = (
            f"[{label}] {hit.chunk.title} | {hit.chunk.section_path} | "
            f"版本 {hit.chunk.version} | chunk:{hit.chunk.chunk_id}\n{hit.chunk.text}"
        )
        if max_distance is not None and hit.distance is not None and hit.distance > max_distance:
            reason = "distance"
        elif hit.chunk.content_hash in seen:
            reason = "duplicate"
        elif hit.chunk.chunk_id not in selected_ids:
            reason = "rank_budget"
        elif len("\n\n".join([*sections, block])) > max_chars:
            reason = "context_budget"
        else:
            source_id = label
            seen.add(hit.chunk.content_hash)
            sections.append(block)
            sources.append(KnowledgeSource(**hit.chunk.model_dump(), source_id=label))
        candidates.append(
            CandidateEvidence(
                rank=rank,
                chunk=hit.chunk,
                distance=hit.distance,
                reason=reason,
                source_id=source_id,
                contributions=hit.contributions,
                fusion_score=hit.fusion_score,
            )
        )
    return PreparedKnowledge(
        query=result.query,
        manifest=result.manifest,
        candidates=tuple(candidates),
        sources=tuple(sources),
        injected_context="\n\n".join(sections),
        distance_filter="disabled" if max_distance is None else "enabled",
        retrieval_mode=result.retrieval_mode,
        retrieval_signature=result.retrieval_signature,
        route_timings_ms=result.route_timings_ms,
    )


def resolve_citations(
    content: str, prepared: PreparedKnowledge | None
) -> tuple[str, tuple[KnowledgeSource, ...]]:
    """只保留本轮实际注入的引用；未知编号不生成来源或读磁盘。

    Args:
        content: 模型最终回复，不是未完成增量。
        prepared: 本轮实际供给的证据；未检索时为 None，所有 K 引用均不可核验。
    Returns:
        标注不可核验引用后的文本和去重引用快照。
    """
    allowed = {source.source_id: source for source in prepared.sources} if prepared else {}
    cited: dict[str, KnowledgeSource] = {}

    def replace(match: re.Match[str]) -> str:
        source_id = match.group(1)
        if source_id not in allowed:
            return "[来源不可核验]"
        cited[source_id] = allowed[source_id]
        return match.group(0)

    return re.sub(r"\[(K\d+)\]", replace, content), tuple(cited.values())
