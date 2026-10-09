"""知识应用的分词、编码和快照存储边界；不加载第三方 SDK。"""

from typing import Protocol

from .domain import BuildResult, IndexManifest, KnowledgeChunk, SearchHit


class EmbeddingPort(Protocol):
    """真实或测试编码契约；签名覆盖模型及输入约定，不只比较维度。"""

    signature: str
    dimensions: int

    def token_count(self, text: str) -> int:
        """计数完整输入，包含特殊 token，不截断。"""
        ...

    def passages(self, texts: list[str]) -> list[list[float]]:
        """按顺序编码文档；返回每段的向量。"""
        ...

    def query(self, text: str) -> list[float]:
        """编码单个查询；返回向量，不生成答案。"""
        ...


class IndexPort(Protocol):
    """版本快照契约；实现负责持久化、核验及原子发布。"""

    def find(self, fingerprint: str, signature: str) -> IndexManifest | None:
        """查找可复用快照；不存在返回 None，不自动创建。"""
        ...

    def publish(
        self,
        manifest: IndexManifest,
        chunks: tuple[KnowledgeChunk, ...],
        vectors: list[list[float]],
    ) -> BuildResult:
        """发布核验后的快照；失败保留原有效版本。"""
        ...

    def current(self, signature: str) -> IndexManifest:
        """加载兼容的当前快照；缺库或不兼容报错。"""
        ...

    def read_chunks(self, manifest: IndexManifest) -> tuple[KnowledgeChunk, ...]:
        """读取指定快照完整片段供离线评测，不重新构建。"""
        ...

    def query(
        self, manifest: IndexManifest, vector: list[float], top_k: int
    ) -> tuple[SearchHit, ...]:
        """以显式向量查询指定快照，返回原始距离与片段。"""
        ...


class LexicalPort(Protocol):
    """已绑定同一片段快照的词法召回边界；不负责加载原文。"""

    signature: str

    def query(self, query: str, top_k: int) -> tuple[SearchHit, ...]:
        """返回有词项匹配的候选及原始排名、BM25分数。"""
        ...
