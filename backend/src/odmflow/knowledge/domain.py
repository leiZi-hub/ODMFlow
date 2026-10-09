"""知识文档、片段与索引结果契约；不依赖解析、模型或向量库 SDK。"""

import hashlib
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeError(ValueError):
    """可展示的知识配置、资料或索引错误，不携带密钥。"""


class KnowledgeQueryTooLong(KnowledgeError):
    """完整检索问题超过 Embedding token 限额，允许调用方选择有界精简。"""


class KnowledgeDocument(BaseModel):
    """已校验的合成原文；不是客户业务事实。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    doc_id: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    version: str = Field(min_length=1)
    updated_at: date
    classification: Literal["synthetic-learning"]
    region: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_path: str
    source_hash: str
    body: str = Field(min_length=1)


class KnowledgeChunk(BaseModel):
    """带可追溯出处的不可变片段；不保存向量或用户信息。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    chunk_id: str
    doc_id: str = Field(min_length=1, pattern=r"^[a-z0-9-]+$")
    version: str = Field(min_length=1)
    updated_at: str = Field(min_length=1)
    classification: Literal["synthetic-learning"]
    region: str = Field(min_length=1)
    title: str = Field(min_length=1)
    section_path: str = Field(min_length=1)
    source_path: str = Field(pattern=r"^[a-z][a-z0-9-]*\.md$")
    content_hash: str
    text: str = Field(min_length=1)
    token_count: int = Field(gt=0)


class IndexManifest(BaseModel):
    """完成快照的兼容与完整性清单，不是可修改业务记录。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: Literal[2] = 2
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_signature: str
    dimensions: int = Field(gt=0)
    chunk_ids: tuple[str, ...] = Field(min_length=1)
    chunk_digests: tuple[str, ...] = Field(min_length=1)
    snapshot: str = Field(pattern=r"^[0-9a-f]{64}-[0-9a-f]{8}$")

    @model_validator(mode="after")
    def validate_chunk_manifest(self) -> IndexManifest:
        """绑定一一对应的片段摘要，拒绝缺失或重复标识的清单。"""
        if (
            len(self.chunk_ids) != len(self.chunk_digests)
            or len(set(self.chunk_ids)) != len(self.chunk_ids)
            or not self.snapshot.startswith(self.fingerprint + "-")
        ):
            raise ValueError("片段清单不完整或快照指纹不一致")
        return self


def chunk_digest(chunk: KnowledgeChunk) -> str:
    """摘要绑定原文与全部来源元数据，防止仅改出处仍通过正文校验。

    Args:
        chunk: 已校验片段。
    Returns:
        固定字段序列的 SHA-256。
    """
    return hashlib.sha256(chunk.model_dump_json().encode()).hexdigest()


class BuildResult(BaseModel):
    """一次构建或复用的结果；不宣称检索准确率。"""

    manifest: IndexManifest
    reused: bool


type RetrievalMode = Literal["vector", "bm25", "hybrid"]


class RouteContribution(BaseModel):
    """一条召回路的原排名及原始分数；不同路的score不能直接相加。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    route: Literal["vector", "bm25"]
    rank: int = Field(ge=1)
    score: float = Field(allow_inf_nan=False)


class SearchHit(BaseModel):
    """候选原文、可空cosine距离及融合贡献；均不是答案正确概率。"""

    chunk: KnowledgeChunk
    distance: float | None
    contributions: tuple[RouteContribution, ...] = ()
    fusion_score: float | None = Field(default=None, allow_inf_nan=False)


class SearchResult(BaseModel):
    """某个索引版本的检索基线结果，不是模型答案。"""

    query: str
    manifest: IndexManifest
    hits: tuple[SearchHit, ...]
    candidates: tuple[SearchHit, ...] = ()
    retrieval_mode: RetrievalMode = "vector"
    retrieval_signature: str = "vector-cosine-v1"
    route_timings_ms: dict[str, float] = Field(default_factory=dict)
