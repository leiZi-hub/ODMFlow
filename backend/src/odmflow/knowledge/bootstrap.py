"""离线知识组合根；显式注入模型、切分和 Chroma，不改 FastAPI 启动流程。"""

from importlib.metadata import version
from typing import Literal

from .application import KnowledgeService
from .chunking import OVERLAP_SPLIT_VERSION, SPLIT_VERSION, split_documents, split_documents_overlap
from .configuration import KnowledgeSettings
from .embeddings import LocalEmbedding
from .lexical_index import Bm25Index
from .vector_index import ChromaIndex


def build_knowledge_service(
    settings: KnowledgeSettings, split_strategy: Literal["v3", "v4"] = "v3"
) -> KnowledgeService:
    """组装本地知识用例，不下载或自动建库。

    Args:
        settings: 已验证本地资源配置。
        split_strategy: v3基线或v4章节递归重叠；签名进入索引指纹。
    Returns:
        复用单份模型的离线用例。
    Raises:
        KnowledgeError: 模型缺失或非法；导入缺少 extra 时由 CLI 提示。
    """
    splitter = split_documents if split_strategy == "v3" else split_documents_overlap
    signature = SPLIT_VERSION if split_strategy == "v3" else OVERLAP_SPLIT_VERSION
    return KnowledgeService(
        LocalEmbedding(settings.model_directory),
        ChromaIndex(settings.resource_root),
        splitter,
        split_signature=f"{signature}:langchain-text-splitters={version('langchain-text-splitters')}",
        lexical_factory=Bm25Index,
        retrieval_mode=settings.retrieval_mode,
        candidate_k=settings.candidate_k,
        rrf_constant=settings.rrf_constant,
    )
