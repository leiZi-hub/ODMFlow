"""离线知识资源配置；只读取当前命令的环境，不隐式加载 .env 或创建目录。"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from odmflow.configuration import RagSettings

from .domain import KnowledgeError, RetrievalMode


@dataclass(frozen=True)
class KnowledgeSettings:
    """单一资源根及派生模型位置，不包含 Chat Key 或业务数据库。"""

    resource_root: Path
    retrieval_mode: RetrievalMode = "vector"
    candidate_k: int = 10
    rrf_constant: int = 60

    @property
    def model_directory(self) -> Path:
        """返回所选模型的本地目录，不触发下载。"""
        return self.resource_root / "models" / "bge-small-zh-v1.5-onnx"

    @classmethod
    def from_environment(
        cls, policy: RagSettings, environment: Mapping[str, str] | None = None
    ) -> KnowledgeSettings:
        """读取并验证资源根。

        Args:
            policy: 已加载共享策略，只从环境获取资源根。
            environment: 可注入的环境映射；默认进程环境。
        Returns:
            已验证配置；实际文件由模型/索引适配器继续验证。
        Raises:
            KnowledgeError: 未填写、非绝对路径或不是现有目录。
        """
        env = os.environ if environment is None else environment
        value = env.get("ODMFLOW_RAG_ROOT", "")
        path = Path(value)
        if not value.strip() or not path.is_absolute() or not path.is_dir():
            raise KnowledgeError("请在 .env 填写 ODMFLOW_RAG_ROOT 为现有资源根的绝对路径")
        mode = policy.retrieval_mode
        candidates = policy.candidate_k
        constant = policy.rrf_constant
        if (
            mode not in {"vector", "bm25", "hybrid"}
            or not 1 <= candidates <= 20
            or not 1 <= constant <= 1000
        ):
            raise KnowledgeError("检索模式或候选/RRF参数非法")
        return cls(path.resolve(), mode, candidates, constant)
