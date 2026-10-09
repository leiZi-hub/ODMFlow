"""BM25本地适配：从已核验快照派生内存统计，不保存权威资料或引入搜索服务。"""

import math

from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

from .domain import KnowledgeChunk, KnowledgeError, RouteContribution, SearchHit
from .tokenization import TOKENIZATION_SIGNATURE, tokenize


class Bm25Index:
    """小语料逐片段评分；不是面向大规模查询的完整倒排搜索引擎。"""

    signature = f"rank-bm25=0.2.2:okapi:k1=1.5:b=0.75:epsilon=0.25:{TOKENIZATION_SIGNATURE}"

    def __init__(self, chunks: tuple[KnowledgeChunk, ...]) -> None:
        """注入同一快照完整片段并构建统计。

        Args:
            chunks: 已经通过快照完整性检查的目录；不得用新原文替换。
        Raises:
            KnowledgeError: 空目录、重复ID或没有可分词内容。
        """
        tokens = [list(tokenize(chunk.text)) for chunk in chunks]
        if not chunks or len({c.chunk_id for c in chunks}) != len(chunks) or not any(tokens):
            raise KnowledgeError("词法目录为空或标识重复")
        self._chunks = chunks
        self._tokens = [set(items) for items in tokens]
        self._bm25 = BM25Okapi(tokens, k1=1.5, b=0.75, epsilon=0.25)

    def query(self, query: str, top_k: int) -> tuple[SearchHit, ...]:
        """返回有词项重合的候选；零重合不填充，占分高低不是概率。

        Args:
            query: 与资料一致预处理的查询。
            top_k: 1–20候选预算。
        Returns:
            score降序、同分按chunk_id稳定排序；词法独有距离为空。
        Raises:
            KnowledgeError: 数量预算或依赖结果非法。
        """
        if not 1 <= top_k <= 20:
            raise KnowledgeError("词法候选预算必须为1–20")
        tokens = tokenize(query)
        if not tokens:
            return ()
        scores = self._bm25.get_scores(list(tokens))
        matches = [
            (self._chunks[n], float(score))
            for n, score in enumerate(scores)
            if self._tokens[n].intersection(tokens)
        ]
        if any(not math.isfinite(score) for _, score in matches):
            raise KnowledgeError("词法分数非法")
        matches.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return tuple(
            SearchHit(
                chunk=chunk,
                distance=None,
                contributions=(RouteContribution(route="bm25", rank=rank, score=score),),
            )
            for rank, (chunk, score) in enumerate(matches[:top_k], 1)
        )
