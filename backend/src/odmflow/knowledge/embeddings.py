"""本地中文 ONNX 编码适配；验证模型与 tokenizer 文件，不下载模型或调用 Chat API。"""

import hashlib
import json
from importlib.metadata import version
from pathlib import Path

from .domain import KnowledgeError

MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_SHA256 = "1294ea4b6331115a353d81f96b85e8c8d7fdcc284453d5b2fab5b016230aad38"
MODEL_FILES = (
    "model_optimized.onnx",
    "config.json",
    "ort_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
)


class LocalEmbedding:
    """512 维 CPU 编码器；不生成回复，不训练模型，不在导入时加载权重。"""

    dimensions = 512

    def __init__(self, model_directory: Path):
        """验证已准备文件并一次加载推理对象。

        Args:
            model_directory: 包含所选 ONNX 和 tokenizer 的本地目录。
        Raises:
            KnowledgeError: 缺文件、清单不符或模型校验失败。
        """
        try:
            manifest = json.loads(
                (model_directory / "MODEL-MANIFEST.json").read_text(encoding="utf-8")
            )
            hashes = {name: self._file_hash(model_directory / name) for name in MODEL_FILES}
            if (
                manifest["model_id"] != MODEL_ID
                or manifest["dimensions"] != self.dimensions
                or hashes["model_optimized.onnx"] != MODEL_SHA256
            ):
                raise KnowledgeError("本地模型身份或文件校验不符")
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
            raise KnowledgeError("模型资源未准备完整，请按 README 准备所选本地模型") from error
        from fastembed import TextEmbedding
        from tokenizers import Tokenizer

        self.signature = hashlib.sha256(
            json.dumps(
                {
                    "model_id": MODEL_ID,
                    "files": hashes,
                    "dimensions": self.dimensions,
                    "runtime": {
                        name: version(name) for name in ("fastembed", "onnxruntime", "tokenizers")
                    },
                    "format": "onnx-cpu-float32-l2-normalized",
                    "preprocessing": "fastembed-onnx-passage-and-query-no-prefix-v1",
                    "token_limit": 512,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        self._tokenizer = Tokenizer.from_file(str(model_directory / "tokenizer.json"))
        # 用独立分词器计数，关闭默认 truncation/padding，避免把已截断长度误当原长度。
        self._tokenizer.no_truncation()
        self._tokenizer.no_padding()
        self._model = TextEmbedding(
            model_name=MODEL_ID,
            specific_model_path=str(model_directory),
            cache_dir=str(model_directory.parent.parent / "cache"),
            local_files_only=True,
            threads=2,
            providers=["CPUExecutionProvider"],
        )

    @staticmethod
    def _file_hash(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def token_count(self, text: str) -> int:
        """返回完整输入的 token 数，包括 CLS/SEP，不做静默截断。

        Args:
            text: 将交给模型的完整文本。
        Returns:
            未截断 token 数。
        """
        return len(self._tokenizer.encode(text, add_special_tokens=True).ids)

    def passages(self, texts: list[str]) -> list[list[float]]:
        """按 SDK 的 passage 约定编码，本版无额外前缀。

        Args:
            texts: 有效非空片段列表。
        Returns:
            顺序一致的 512 维向量。
        Raises:
            KnowledgeError: 空文本或完整输入超过 512 token。
        """
        if not texts or any(not text.strip() or self.token_count(text) > 512 for text in texts):
            raise KnowledgeError("文档模型输入为空或超过 512 token，禁止截断")
        return [vector.tolist() for vector in self._model.passage_embed(texts, batch_size=16)]

    def query(self, text: str) -> list[float]:
        """使用与文档兼容的 query 约定。

        Args:
            text: 当前检索问题，不含用户身份或密钥。
        Returns:
            512 维查询向量。
        Raises:
            KnowledgeError: 输入为空或超过模型 token 限制。
        """
        if not text.strip() or self.token_count(text) > 512:
            raise KnowledgeError("查询模型输入为空或超过 512 token，禁止截断")
        return [float(value) for value in next(iter(self._model.query_embed(text)))]
