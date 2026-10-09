"""按 Markdown 章节和段落切分，长表格重复表头；不静默截断模型输入。"""

import hashlib
import re
from collections.abc import Callable, Sequence

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from .domain import KnowledgeChunk, KnowledgeDocument, KnowledgeError

SPLIT_VERSION = "markdown-block-embedded-table-rows-v3-no-overlap"
OVERLAP_SPLIT_VERSION = "markdown-section-recursive-zh-v4-overlap64"


def _bounded_parts(
    text: str, prefix: str, count: Callable[[str], int], budget: int, overlap: bool = False
) -> list[str]:
    lines = text.splitlines()
    for separator in range(1, len(lines)):
        cells = lines[separator].strip().strip("|").split("|")
        if "|" not in lines[separator - 1] or not all(
            re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells
        ):
            continue
        start = separator - 1
        end = separator + 1
        while end < len(lines) and "|" in lines[end]:
            end += 1
        header = "\n".join(lines[start : separator + 1]) + "\n"
        rows = [header + line for line in lines[separator + 1 : end]]
        if not rows or any(count(prefix + row) > budget for row in rows):
            raise KnowledgeError("表格单行含标题/表头后超出 token 预算，请人工拆分原文")
        before = (
            _bounded_parts("\n".join(lines[:start]), prefix, count, budget, overlap)
            if start
            else []
        )
        after = (
            _bounded_parts("\n".join(lines[end:]), prefix, count, budget, overlap)
            if end < len(lines)
            else []
        )
        return [*before, *rows, *after]
    if not text.strip():
        return []
    if count(prefix + text) <= budget:
        return [text]
    if overlap:
        prefix_tokens = count(prefix)
        body_budget = budget - prefix_tokens
        if body_budget < 1:
            raise KnowledgeError("标题本身超出token预算")
        recursive = RecursiveCharacterTextSplitter(
            chunk_size=body_budget,
            chunk_overlap=min(64, body_budget // 3),
            length_function=lambda value: max(0, count(prefix + value) - prefix_tokens),
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
            keep_separator="end",
        )
        recursive_parts = recursive.split_text(text)
        if not recursive_parts or any(count(prefix + part) > budget for part in recursive_parts):
            raise KnowledgeError("递归切分后完整输入仍超出token预算，未截断原文")
        return recursive_parts
    parts: list[str] = []
    current: list[str] = []
    for line in lines:
        if count(prefix + line) > budget:
            raise KnowledgeError("单行含标题/表头后超出 token 预算，请人工拆分原文")
        if current and count(prefix + "\n".join([*current, line])) > budget:
            parts.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        parts.append("\n".join(current))
    if not parts:
        raise KnowledgeError("片段无法在 token 预算内安全拆分")
    return parts


def split_documents(
    documents: Sequence[KnowledgeDocument],
    token_count: Callable[[str], int],
    max_tokens: int = 480,
) -> tuple[KnowledgeChunk, ...]:
    """切出带来源的稳定片段，所有标题也计入预算。

    Args:
        documents: 已验证文档。
        token_count: 对完整输入计数的分词器，含特殊 token。
        max_tokens: 单片段上限；默认 480，为模型 512 上限留余量。
    Returns:
        非空且不重复的来源片段。
    Raises:
        KnowledgeError: 没有正文或单行无法安全拆分。
    """
    return _split(documents, token_count, max_tokens, overlap=False)


def split_documents_overlap(
    documents: Sequence[KnowledgeDocument], token_count: Callable[[str], int], max_tokens: int = 480
) -> tuple[KnowledgeChunk, ...]:
    """按章节聚合再递归重叠正文；表格行单独保留表头。

    Args:
        documents: 已验证的来源。
        token_count: 完整模型输入的实际token计数。
        max_tokens: 含标题和特殊token的预算，默认480。
    Returns:
        带来源的片段，正文最多约64token重叠。
    Raises:
        KnowledgeError: 表格单行或标题无法安全保留。
    """
    return _split(documents, token_count, max_tokens, overlap=True)


def _split(
    documents: Sequence[KnowledgeDocument],
    token_count: Callable[[str], int],
    max_tokens: int,
    overlap: bool,
) -> tuple[KnowledgeChunk, ...]:
    """在两种策略之间复用来源构造，签名由组合根显式选择。"""
    splitter = MarkdownHeaderTextSplitter(
        [("#" * level, f"h{level}") for level in range(1, 7)],
        return_each_line=not overlap,
    )
    chunks: list[KnowledgeChunk] = []
    for document in documents:
        for ordinal, block in enumerate(splitter.split_text(document.body)):
            section = " / ".join(str(block.metadata[key]) for key in sorted(block.metadata))
            section = section or document.title
            prefix = f"{document.title}\n章节：{section}\n\n"
            for part_no, part in enumerate(
                _bounded_parts(
                    block.page_content,
                    prefix,
                    token_count,
                    max_tokens,
                    overlap,
                )
            ):
                text = prefix + part
                digest = hashlib.sha256(text.encode()).hexdigest()
                identity = f"{document.doc_id}|{document.version}|{ordinal}|{part_no}|{digest}"
                chunks.append(
                    KnowledgeChunk(
                        chunk_id=hashlib.sha256(identity.encode()).hexdigest(),
                        doc_id=document.doc_id,
                        version=document.version,
                        updated_at=document.updated_at.isoformat(),
                        classification=document.classification,
                        region=document.region,
                        title=document.title,
                        section_path=section,
                        source_path=document.source_path,
                        content_hash=digest,
                        text=text,
                        token_count=token_count(text),
                    )
                )
    if not chunks:
        raise KnowledgeError("语料没有可用正文片段")
    return tuple(chunks)
