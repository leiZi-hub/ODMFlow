"""RAG调试快照字节预算：只裁候选预览，不改变可信来源/真实注入或检索排名。"""

import json

from odmflow.knowledge.domain import KnowledgeError

from ..tools.rag.evidence import PreparedKnowledge

# 留32KiB给操作描述、摘要和公开来源；完整封装仍在operation_payload检查128KiB。
MAX_DETAIL_BYTES = 96 * 1024


class KnowledgeTraceTooLarge(KnowledgeError):
    """真实选用证据和元数据已超预算，不能用截断正文伪造完整快照。"""


def project_rag_trace(prepared: PreparedKnowledge) -> str:
    """序列化完整详情；超预算时公平分配候选正文预览字节。

    Args:
        prepared: 不可变的真实检索/注入结果，函数不会修改它。
    Returns:
        有明确preview_truncated/original_chars标记的JSON；sources/context始终完整。
    Raises:
        KnowledgeTraceTooLarge: 即使移除候选预览，必要证据仍超预算。
    """
    details = json.loads(prepared.model_dump_json())
    details["candidate_preview_policy"] = "full-or-json-utf8-budget-v1"
    for candidate in details["candidates"]:
        candidate["preview_truncated"] = False
        candidate["preview_original_chars"] = len(candidate["chunk"]["text"])
    encoded = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) <= MAX_DETAIL_BYTES:
        return encoded
    originals = [candidate["chunk"]["text"] for candidate in details["candidates"]]
    for candidate in details["candidates"]:
        candidate["chunk"]["text"] = ""
        candidate["preview_truncated"] = True
    essential = json.dumps(details, ensure_ascii=False, separators=(",", ":"))
    # true改回false增加1字节，预留每条1字节，避免恰好填满后的封装超限。
    remaining = MAX_DETAIL_BYTES - len(essential.encode("utf-8")) - len(originals)
    if remaining < 0 or not originals:
        raise KnowledgeTraceTooLarge("完整知识证据超过调试快照预算，请降低上下文/候选预算")
    allowance = remaining // len(originals)
    for candidate, original in zip(details["candidates"], originals, strict=True):
        # 按JSON转义后的实际UTF-8字节计数，不能用字符数冒充存储大小。
        low, high = 0, len(original)
        while low < high:
            middle = (low + high + 1) // 2
            size = len(json.dumps(original[:middle], ensure_ascii=False).encode("utf-8")) - 2
            if size <= allowance:
                low = middle
            else:
                high = middle - 1
        candidate["chunk"]["text"] = original[:low]
        candidate["preview_truncated"] = low < len(original)
    return json.dumps(details, ensure_ascii=False, separators=(",", ":"))
