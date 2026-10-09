"""构建器调用的独立进程核验入口；只开已有快照，不加载模型、发布指针或读取 .env。"""

import argparse
from pathlib import Path

from .domain import KnowledgeError
from .vector_index import ChromaIndex


def main() -> int:
    """核验指定快照，成功返回 0，错误返回 2，不输出原文或敏感环境。"""
    parser = argparse.ArgumentParser(description="内部索引核验进程")
    parser.add_argument("root", type=Path)
    parser.add_argument("snapshot")
    parser.add_argument("signature")
    parser.add_argument("--pending", action="store_true")
    args = parser.parse_args()
    try:
        ChromaIndex(args.root).verify_snapshot(args.snapshot, args.signature, args.pending)
    except KnowledgeError, OSError, ValueError, RuntimeError:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
