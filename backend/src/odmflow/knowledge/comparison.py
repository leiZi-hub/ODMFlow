"""同快照三策略比较用例；复用评测器，不加载模型SDK、生成答案或写报告文件。"""

from pydantic import BaseModel

from .application import KnowledgeService
from .domain import IndexManifest, KnowledgeChunk, RetrievalMode, SearchResult
from .evaluation import EvaluationDataset, EvaluationReport, evaluate


class RetrievalComparison(BaseModel):
    """冻结题集的三策略报告；热缓存顺序测试，不代表生产延迟或答案准确率。"""

    schema_version: int = 1
    timing_scope: str = "warm sequential local retrieval; one unscored warmup per mode"
    reports: tuple[EvaluationReport, ...]


class SelectedModeRetrieval:
    """评测的固定模式适配；不改在线service的默认策略。"""

    def __init__(self, service: KnowledgeService, mode: RetrievalMode) -> None:
        """注入同一个已经固定快照的服务及显式策略。"""
        self._service, self._mode = service, mode

    def inspect_index(self) -> tuple[IndexManifest, tuple[KnowledgeChunk, ...]]:
        """读取固定快照，供人工标注映射。"""
        return self._service.inspect_index()

    def search(self, query: str, top_k: int = 3) -> SearchResult:
        """查询同一服务，不创建新模型或切换快照。"""
        return self._service.search(query, top_k, mode=self._mode)


def compare(
    service: KnowledgeService, dataset: EvaluationDataset, top_k: int = 3
) -> RetrievalComparison:
    """固定一次快照并按同题同K评测三种策略。

    Args:
        service: 已组装同源向量和词法的本地知识用例。
        dataset: 结果出来前冻结的人工题集。
        top_k: 各路最终评分预算，1–20。
    Returns:
        vector/bm25/hybrid报告；质量未过仍返回，标注或依赖故障显式抛错。
    """
    service.initialize_query()
    reports = []
    modes: tuple[RetrievalMode, ...] = ("vector", "bm25", "hybrid")
    for mode in modes:
        selected = SelectedModeRetrieval(service, mode)
        selected.search(dataset.cases[0].query, top_k)
        reports.append(evaluate(selected, dataset, top_k))
    return RetrievalComparison(reports=tuple(reports))
