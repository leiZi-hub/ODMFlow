"""离线知识构建与查询用例；仅通过端口调用分词/向量存储，无框架或 HTTP 依赖。"""

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from time import perf_counter
from uuid import uuid4

from .domain import (
    BuildResult,
    IndexManifest,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeError,
    KnowledgeQueryTooLong,
    RetrievalMode,
    RouteContribution,
    SearchHit,
    SearchResult,
    chunk_digest,
)
from .fusion import reciprocal_rank_fusion, unique_top_hits
from .ports import EmbeddingPort, IndexPort, LexicalPort

type ChunkSplitter = Callable[
    [Sequence[KnowledgeDocument], Callable[[str], int], int], tuple[KnowledgeChunk, ...]
]


class KnowledgeService:
    """编排人工触发的索引与预览，不承担聊天路由或业务写入。"""

    def __init__(
        self,
        embedding: EmbeddingPort,
        index: IndexPort,
        splitter: ChunkSplitter,
        max_tokens: int = 480,
        split_signature: str | None = None,
        *,
        lexical_factory: Callable[[tuple[KnowledgeChunk, ...]], LexicalPort] | None = None,
        retrieval_mode: RetrievalMode = "vector",
        candidate_k: int = 10,
        rrf_constant: int = 60,
    ):
        """注入编码、存储和检索策略；构造时不触发索引读写。

        Args:
            embedding: 向量编码端口（词法查询不调用query编码）。
            index: 已验证的快照存储端口。
            splitter: 离线切分策略，不参与在线查询。
            max_tokens: 构建片段完整输入token预算。
            split_signature: 策略版本，进入构建指纹。
            lexical_factory: 从同一完整目录派生词法索引；None只支持向量。
            retrieval_mode: 默认策略，可在离线对比时单次覆盖。
            candidate_k: 混合每路召回预算，实际不小于最终K。
            rrf_constant: 排名融合平滑常量。
        Raises:
            KnowledgeError: 策略、候选预算或融合参数非法。
        """
        self._embedding = embedding
        self._index = index
        self._splitter = splitter
        self._max_tokens = max_tokens
        self._split_signature = split_signature or f"{splitter.__module__}.{splitter.__qualname__}"
        self._query_manifest: IndexManifest | None = None
        if (
            retrieval_mode not in {"vector", "bm25", "hybrid"}
            or not 1 <= candidate_k <= 20
            or not 1 <= rrf_constant <= 1000
        ):
            raise KnowledgeError("检索参数非法")
        self._lexical_factory = lexical_factory
        self._lexical: LexicalPort | None = None
        self.retrieval_mode = retrieval_mode
        self._candidate_k, self._rrf_constant = candidate_k, rrf_constant

    def initialize_query(self) -> None:
        """一次核验并固定当前索引；新构建版本须重启在线服务才能激活。"""
        self._query_manifest = self._index.current(self._embedding.signature)
        self._lexical = None
        if self._lexical_factory is not None:
            self._lexical = self._lexical_factory(self._index.read_chunks(self._query_manifest))

    def validate_query(self, query: str) -> None:
        """检查完整输入长度；不截断、不调用编码或数据库。

        Args:
            query: 待检索的完整问题。
        Raises:
            KnowledgeError: 问题为空。
            KnowledgeQueryTooLong: 本地 tokenizer 计数超过 512 token。
        """
        if not query.strip():
            raise KnowledgeError("查询必须非空")
        if self._embedding.token_count(query) > 512:
            raise KnowledgeQueryTooLong("查询不得超过 512 token")

    def _validate_vectors(self, vectors: list[list[float]], count: int) -> None:
        if len(vectors) != count or any(
            len(vector) != self._embedding.dimensions
            or not all(math.isfinite(number) for number in vector)
            or sum(number * number for number in vector) <= 0
            for vector in vectors
        ):
            raise KnowledgeError("编码结果的数量、维度或数值不合法")

    def build(self, documents: Sequence[KnowledgeDocument]) -> BuildResult:
        """构建/复用完整快照，不修改旧版本。

        Args:
            documents: 已校验原文，切分策略由组合根注入。
        Returns:
            完成快照及是否复用。
        Raises:
            KnowledgeError: 空/非法片段、编码错误或索引完整性错误。
        """
        if not 1 <= self._max_tokens <= 512:
            raise KnowledgeError("片段 token 预算必须在 1 到 512 之间")
        chunks = self._splitter(documents, self._embedding.token_count, self._max_tokens)
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "index_schema": 2,
                    "model": self._embedding.signature,
                    "dimensions": self._embedding.dimensions,
                    "split": self._split_signature,
                    "budget": self._max_tokens,
                    "metric": "cosine",
                    "sources": [(doc.source_path, doc.source_hash) for doc in documents],
                    "chunks": [(chunk.chunk_id, chunk.token_count) for chunk in chunks],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        existing = self._index.find(fingerprint, self._embedding.signature)
        if existing is not None:
            # 再通过 publish 完成独占核验与指针激活；复用不重复编码。
            return self._index.publish(existing, chunks, [])
        vectors = self._embedding.passages([chunk.text for chunk in chunks])
        self._validate_vectors(vectors, len(chunks))
        manifest = IndexManifest(
            fingerprint=fingerprint,
            model_signature=self._embedding.signature,
            dimensions=self._embedding.dimensions,
            chunk_ids=tuple(c.chunk_id for c in chunks),
            chunk_digests=tuple(chunk_digest(chunk) for chunk in chunks),
            snapshot=f"{fingerprint}-{uuid4().hex[:8]}",
        )
        return self._index.publish(manifest, chunks, vectors)

    def inspect_index(self) -> tuple[IndexManifest, tuple[KnowledgeChunk, ...]]:
        """读取当前核验快照及完整片段，供离线评测定位人工证据。

        Returns:
            同一快照的清单和片段，不重新加载原资料或编码。
        Raises:
            KnowledgeError: 索引不存在、不兼容或不完整。
        """
        manifest = self._query_manifest or self._index.current(self._embedding.signature)
        return manifest, self._index.read_chunks(manifest)

    def search(
        self, query: str, top_k: int = 3, *, mode: RetrievalMode | None = None
    ) -> SearchResult:
        """查询已完成索引并保留原始贡献；不保证存在答案。

        Args:
            query: 非空问题，完整输入至多 512 token。
            top_k: 返回条数，1 到 20。
            mode: 单次显式覆盖；None沿用环境配置的默认模式。
        Returns:
            同一版本的最终Top-K、更宽候选、召回路原评分/耗时。
        Raises:
            KnowledgeError: 查询无效、索引不存在或模型不兼容。
        """
        query = query.strip()
        if not 1 <= top_k <= 20:
            raise KnowledgeError("top_k 必须在 1 到 20 之间")
        self.validate_query(query)
        active_mode = mode or self.retrieval_mode
        if active_mode not in {"vector", "bm25", "hybrid"}:
            raise KnowledgeError("检索模式非法")
        # 混合/词法需要完整已核验目录；只在初始化派生索引，不每次重新分词原文件。
        if active_mode != "vector" and self._query_manifest is None:
            self.initialize_query()
        manifest = self._query_manifest or self._index.current(self._embedding.signature)
        count = max(top_k, self._candidate_k) if active_mode == "hybrid" else top_k
        routes: list[tuple[SearchHit, ...]] = []
        timings: dict[str, float] = {}
        if active_mode != "bm25":
            start = perf_counter()
            vector = self._embedding.query(query)
            self._validate_vectors([vector], 1)
            vector_hits = self._index.query(manifest, vector, count)
            if any(hit.distance is None for hit in vector_hits):
                raise KnowledgeError("向量召回缺少距离")
            routes.append(
                tuple(
                    hit.model_copy(
                        update={
                            "contributions": (
                                RouteContribution(route="vector", rank=rank, score=hit.distance),
                            )
                        }
                    )
                    for rank, hit in enumerate(vector_hits, 1)
                    if hit.distance is not None
                )
            )
            timings["vector"] = (perf_counter() - start) * 1000
        if active_mode != "vector":
            if self._lexical is None:
                raise KnowledgeError("词法召回未配置")
            start = perf_counter()
            routes.append(self._lexical.query(query, count))
            timings["bm25"] = (perf_counter() - start) * 1000
        start = perf_counter()
        candidates = (
            reciprocal_rank_fusion(tuple(routes), constant=self._rrf_constant)
            if active_mode == "hybrid"
            else routes[0]
        )
        hits = unique_top_hits(candidates, top_k) if active_mode == "hybrid" else candidates
        if active_mode == "hybrid":
            timings["fusion"] = (perf_counter() - start) * 1000
        signature = (
            f"mode={active_mode}:candidate_k={count}:rrf={self._rrf_constant}:vector-cosine-v1"
        )
        if active_mode != "vector" and self._lexical is not None:
            signature += ":" + self._lexical.signature
        return SearchResult(
            query=query,
            manifest=manifest,
            hits=hits,
            candidates=candidates,
            retrieval_mode=active_mode,
            retrieval_signature=signature,
            route_timings_ms=timings,
        )
