"""离线检索评测：人工证据定位、片段指标与固定题运行；不判答案、不调用 Chat。"""

import hashlib
from time import perf_counter
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .domain import (
    IndexManifest,
    KnowledgeChunk,
    KnowledgeError,
    RetrievalMode,
    SearchHit,
    SearchResult,
)

type NonBlankText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class EvidenceReference(BaseModel):
    """人工相关性标注，按来源、章节和原文摘录定位；不是生成答案。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    source_path: str = Field(pattern=r"^[a-z][a-z0-9-]*\.md$")
    section_path: NonBlankText
    text: NonBlankText


class EvaluationCase(BaseModel):
    """一条合成评测题；正例标注不进入知识索引，未知题不伪造标准答案。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: NonBlankText
    query: NonBlankText
    expected_source: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*\.md$")
    kind: Literal["acceptance", "diagnostic", "unknown-policy-diagnostic", "unrelated-diagnostic"]
    references: tuple[EvidenceReference, ...] = ()

    @model_validator(mode="after")
    def validate_annotation(self) -> EvaluationCase:
        """正式验收必须有来源与证据；未知/无关题不能混入正例指标。"""
        if self.kind == "acceptance" and (not self.expected_source or not self.references):
            raise ValueError("验收题必须有预期来源和人工证据标注")
        if self.kind in {"unknown-policy-diagnostic", "unrelated-diagnostic"} and self.references:
            raise ValueError("未知或无关题不能配置正例证据")
        return self


class EvaluationDataset(BaseModel):
    """版本化评测题集；仅包含人工标注，不声称覆盖全部真实客户问题。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[1] = 1
    scope: str = Field(min_length=1)
    cases: tuple[EvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_cases(self) -> EvaluationDataset:
        """拒绝重复题号和没有验收题的集合，防止汇总为空仍宣称通过。"""
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("评测题号重复")
        if not any(case.kind == "acceptance" for case in self.cases):
            raise ValueError("至少需要一道验收题")
        return self


class CaseEvaluation(BaseModel):
    """单题排名与标注片段指标；无正例题的指标为空，而不是0或1。"""

    case_id: str
    query: str
    kind: str
    expected_source: str | None
    source_hit: bool | None
    relevant_chunk_ids: tuple[str, ...]
    hits: tuple[SearchHit, ...]
    hit_at_k: int | None
    recall_at_k: float | None
    precision_at_k: float | None
    reciprocal_rank_at_k: float | None
    seconds: float = 0


class EvaluationReport(BaseModel):
    """固定快照的检索报告；不等于答案准确率，汇总只包含 acceptance 题。"""

    schema_version: Literal[1] = 1
    metric_scope: str = "chunk_relevance_from_manual_evidence_annotations"
    dataset_sha256: str
    dataset_scope: str
    manifest: IndexManifest
    top_k: int
    acceptance_total: int
    acceptance_passed: int
    mean_hit_at_k: float
    mean_recall_at_k: float
    mean_precision_at_k: float
    mean_reciprocal_rank_at_k: float
    cases: tuple[CaseEvaluation, ...]
    retrieval_mode: RetrievalMode = "vector"
    retrieval_signature: str = "vector-cosine-v1"
    mean_seconds: float = 0


class RetrievalEvaluationPort(Protocol):
    """评测使用的真实检索边界；允许工程替身，不依赖具体向量库。"""

    def inspect_index(self) -> tuple[IndexManifest, tuple[KnowledgeChunk, ...]]:
        """读取同一索引的完整片段供标注映射，不重新切分语料。"""
        ...

    def search(self, query: str, top_k: int = 3) -> SearchResult:
        """运行实际检索并返回快照及候选。"""
        ...


def score_case(
    case: EvaluationCase, catalog: tuple[KnowledgeChunk, ...], hits: tuple[SearchHit, ...]
) -> CaseEvaluation:
    """依据人工摘录评分，缺失标注显式失败，不偷改召回分母。

    Args:
        case: 标注题目，来源命中与片段命中分开计算。
        catalog: 当前快照的完整片段，不是仅 Top-K 候选。
        hits: 实际召回候选，保持原排名。
    Returns:
        单题来源命中、片段指标和原始候选。
    Raises:
        KnowledgeError: 标注无法定位、片段重复或候选与快照不一致。
    """
    by_id = {chunk.chunk_id: chunk for chunk in catalog}
    if len(by_id) != len(catalog) or len({hit.chunk.chunk_id for hit in hits}) != len(hits):
        raise KnowledgeError("评测出现重复片段标识")
    if any(by_id.get(hit.chunk.chunk_id) != hit.chunk for hit in hits):
        raise KnowledgeError("评测候选不属于当前快照或内容错配")
    if case.expected_source and not any(
        chunk.source_path == case.expected_source for chunk in catalog
    ):
        raise KnowledgeError(f"评测预期来源不存在：{case.id} / {case.expected_source}")
    relevant: set[str] = set()
    for reference in case.references:
        matching = {
            chunk.chunk_id
            for chunk in catalog
            if chunk.source_path == reference.source_path
            and chunk.section_path == reference.section_path
            and reference.text in chunk.text
        }
        if not matching:
            raise KnowledgeError(f"评测标注无法映射：{case.id} / {reference.source_path}")
        relevant.update(matching)
    ranks = [rank for rank, hit in enumerate(hits, 1) if hit.chunk.chunk_id in relevant]
    scored = bool(relevant)
    return CaseEvaluation(
        case_id=case.id,
        query=case.query,
        kind=case.kind,
        expected_source=case.expected_source,
        source_hit=(
            any(hit.chunk.source_path == case.expected_source for hit in hits)
            if case.expected_source
            else None
        ),
        relevant_chunk_ids=tuple(chunk.chunk_id for chunk in catalog if chunk.chunk_id in relevant),
        hits=hits,
        hit_at_k=int(bool(ranks)) if scored else None,
        recall_at_k=len(ranks) / len(relevant) if scored else None,
        precision_at_k=(len(ranks) / len(hits) if hits else 0.0) if scored else None,
        reciprocal_rank_at_k=(1 / ranks[0] if ranks else 0.0) if scored else None,
    )


def evaluate(
    service: RetrievalEvaluationPort, dataset: EvaluationDataset, top_k: int = 3
) -> EvaluationReport:
    """执行固定题集并按验收题宏平均；不跨快照拼接结果。

    Args:
        service: 当前实际检索用例，自动测试可注入替身。
        dataset: 人工标注的固定题集，不写入向量库。
        top_k: 与实际检索一致的候选预算，1至20。
    Returns:
        可保存及比较的报告，质量未通过也正常返回。
    Raises:
        KnowledgeError: 输入/标注无效或评测期间索引切换。
    """
    if not 1 <= top_k <= 20:
        raise KnowledgeError("评测 top_k 必须在1至20之间")
    manifest, catalog = service.inspect_index()
    if len(catalog) != len(manifest.chunk_ids) or {chunk.chunk_id for chunk in catalog} != set(
        manifest.chunk_ids
    ):
        raise KnowledgeError("评测片段清单与快照不一致")
    cases = []
    retrieval_mode: RetrievalMode | None = None
    retrieval_signature: str | None = None
    for case in dataset.cases:
        start = perf_counter()
        result = service.search(case.query, top_k)
        if retrieval_mode is not None and (
            result.retrieval_mode != retrieval_mode
            or result.retrieval_signature != retrieval_signature
        ):
            raise KnowledgeError("评测期间检索策略发生变化")
        retrieval_mode, retrieval_signature = result.retrieval_mode, result.retrieval_signature
        if result.manifest != manifest:
            raise KnowledgeError("评测期间快照发生变化，请重新执行")
        if len(result.hits) > top_k:
            raise KnowledgeError("评测候选数量超过 top_k")
        scored = score_case(case, catalog, result.hits)
        cases.append(scored.model_copy(update={"seconds": perf_counter() - start}))
    acceptance = [case for case in cases if case.kind == "acceptance"]
    total = len(acceptance)
    return EvaluationReport(
        dataset_sha256=hashlib.sha256(dataset.model_dump_json().encode()).hexdigest(),
        dataset_scope=dataset.scope,
        manifest=manifest,
        top_k=top_k,
        acceptance_total=total,
        acceptance_passed=sum(
            case.source_hit is True and case.hit_at_k == 1 for case in acceptance
        ),
        mean_hit_at_k=sum(case.hit_at_k or 0 for case in acceptance) / total,
        mean_recall_at_k=sum(case.recall_at_k or 0 for case in acceptance) / total,
        mean_precision_at_k=sum(case.precision_at_k or 0 for case in acceptance) / total,
        mean_reciprocal_rank_at_k=sum(case.reciprocal_rank_at_k or 0 for case in acceptance)
        / total,
        cases=tuple(cases),
        retrieval_mode=retrieval_mode or "vector",
        retrieval_signature=retrieval_signature or "vector-cosine-v1",
        mean_seconds=sum(case.seconds for case in acceptance) / total,
    )
