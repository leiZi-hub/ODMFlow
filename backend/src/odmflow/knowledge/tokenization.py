"""词法预处理：中文字符双元组与ASCII词/型号归一化；不是语义分词或意图识别。"""

import re
import unicodedata

TOKENIZATION_SIGNATURE = "zh-bigram-ascii-model-v2"


def tokenize(text: str) -> tuple[str, ...]:
    """对资料与query使用完全相同的预处理，不下载词典。

    Args:
        text: 原文或完整查询。
    Returns:
        中文相邻双字、单字以及小写ASCII词；OF T10/OF-T10保留同一型号token。
    """
    normalized = unicodedata.normalize("NFKC", text).lower()
    # Unicode的\b把汉字也当word，中文紧邻型号时不能用它定义ASCII型号边界。
    normalized = re.sub(r"(?<![a-z0-9_])(of)[\s-]+([a-z]\d+)(?![a-z0-9_])", r"\1-\2", normalized)
    tokens: list[str] = []
    for part in re.findall(r"[\u4e00-\u9fff]+|[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
        if re.fullmatch(r"[\u4e00-\u9fff]+", part) and len(part) > 1:
            tokens.extend(part[n : n + 2] for n in range(len(part) - 1))
        else:
            tokens.append(part)
    return tuple(tokens)
