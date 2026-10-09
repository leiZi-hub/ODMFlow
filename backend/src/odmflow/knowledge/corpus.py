"""只读取五份受控 Markdown，验证 YAML 来源；不递归扫描或追随文档链接。"""

import hashlib
import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from .domain import KnowledgeDocument, KnowledgeError

CORPUS_FILES = (
    "company.md",
    "products.md",
    "customization.md",
    "order-policy.md",
    "aftersales-policy.md",
)


def load_corpus(root: Path) -> tuple[KnowledgeDocument, ...]:
    """加载白名单原文并校验来源。

    Args:
        root: 五份资料的目录；文件不可链接到目录外。
    Returns:
        按白名单顺序排列的原文快照。
    Raises:
        KnowledgeError: 文件缺失、路径逃逸、重复来源或元数据不合法。
    """
    documents = []
    seen: set[str] = set()
    for name in CORPUS_FILES:
        path = root / name
        try:
            if path.resolve().parent != root.resolve() or path.is_symlink():
                raise KnowledgeError(f"资料路径不合法：{name}")
            raw = path.read_text(encoding="utf-8-sig")
            match = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", raw, re.DOTALL)
            if match is None:
                raise KnowledgeError(f"资料缺少 YAML 头部：{name}")
            try:
                metadata = yaml.safe_load(match[1])
            except ValueError as error:
                # YAML 的日期构造器可能先于 Pydantic 抛出 ValueError。
                raise KnowledgeError(f"资料 YAML 日期不合法：{name}") from error
            title = re.search(r"^# (.+)$", match[2], re.MULTILINE)
            if not isinstance(metadata, dict) or title is None:
                raise KnowledgeError(f"资料元数据或标题不合法：{name}")
            document = KnowledgeDocument.model_validate(
                {
                    **metadata,
                    "title": title[1].strip(),
                    "source_path": name,
                    "source_hash": hashlib.sha256(raw.encode()).hexdigest(),
                    "body": match[2],
                }
            )
            if document.doc_id in seen:
                raise KnowledgeError(f"重复 doc_id：{document.doc_id}")
            seen.add(document.doc_id)
            documents.append(document)
        except (OSError, UnicodeError, yaml.YAMLError, ValidationError) as error:
            raise KnowledgeError(f"无法读取有效资料：{name}（{type(error).__name__}）") from error
    return tuple(documents)
