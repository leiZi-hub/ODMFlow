"""长期维护的离线 build/search/evaluate 命令；不启动 HTTP、不下载、不读取客户数据。"""

import argparse
import sys
from pathlib import Path
from uuid import uuid4

from odmflow.configuration import load_application_settings

from .domain import KnowledgeError


def main(arguments: list[str] | None = None) -> int:
    """执行构建、检索或固定题评测，输出可 Review 的 JSON。

    Args:
        arguments: 可注入命令参数，默认命令行。
    Returns:
        成功 0；评测验收未过 1；配置/索引/依赖错误 2。
    """
    parser = argparse.ArgumentParser(description="ODMFlow 离线合成知识索引；不是聊天 API")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="校验原文并构建或复用索引")
    build.add_argument("--corpus", type=Path, default=Path("knowledge/corpus"))
    build.add_argument("--split-strategy", choices=("v3", "v4"), default="v3")
    search = commands.add_parser("search", help="预览向量近邻及出处，不生成答案")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=None)
    search.add_argument("--mode", choices=("vector", "bm25", "hybrid"))
    evaluation = commands.add_parser("evaluate", help="运行固定题集并保存检索质量报告")
    evaluation.add_argument("--cases", type=Path, default=Path("knowledge/evaluation-cases.json"))
    evaluation.add_argument("--top-k", type=int, default=None)
    evaluation.add_argument("--mode", choices=("vector", "bm25", "hybrid"))
    comparison = commands.add_parser("compare", help="同快照比较向量、BM25和RRF，不生成答案")
    comparison.add_argument(
        "--cases", type=Path, default=Path("knowledge/evaluation-cases-m5.json")
    )
    comparison.add_argument("--top-k", type=int, default=None)
    options = parser.parse_args(arguments)
    try:
        policy = load_application_settings().rag
        top_k = getattr(options, "top_k", None)
        top_k = policy.top_k if top_k is None else top_k
        from .bootstrap import build_knowledge_service
        from .comparison import RetrievalComparison, SelectedModeRetrieval, compare
        from .configuration import KnowledgeSettings
        from .corpus import load_corpus
        from .evaluation import EvaluationDataset, EvaluationReport, evaluate

        settings = KnowledgeSettings.from_environment(policy)
        if options.command in {"evaluate", "compare"}:
            dataset = EvaluationDataset.model_validate_json(
                options.cases.read_text(encoding="utf-8-sig")
            )
            service = build_knowledge_service(settings)
            report: RetrievalComparison | EvaluationReport
            if options.command == "compare":
                report = compare(service, dataset, top_k)
                passed = all(
                    item.acceptance_passed == item.acceptance_total for item in report.reports
                )
            else:
                if options.mode:
                    service.initialize_query()
                selected = SelectedModeRetrieval(service, options.mode) if options.mode else service
                report = evaluate(selected, dataset, top_k)
                passed = report.acceptance_passed == report.acceptance_total
            output = report.model_dump_json(indent=2)
            directory = settings.resource_root / "artifacts" / "evaluations"
            directory.mkdir(parents=True, exist_ok=True)
            prefix = "compare" if options.command == "compare" else "retrieval"
            path = directory / f"{prefix}-{uuid4().hex}.json"
            with path.open("x", encoding="utf-8") as stream:
                stream.write(output + "\n")
            print(output)
            print(f"评测报告：{path}", file=sys.stderr)
            return 0 if passed else 1
        service = (
            build_knowledge_service(settings, "v4")
            if options.command == "build" and options.split_strategy == "v4"
            else build_knowledge_service(settings)
        )
        result = (
            service.build(load_corpus(options.corpus))
            if options.command == "build"
            else service.search(options.query, top_k, mode=options.mode)
        )
        print(result.model_dump_json(indent=2))
        return 0
    except ImportError:
        print("缺少知识依赖：请执行 uv sync --extra rag --locked", file=sys.stderr)
        return 2
    except (KnowledgeError, OSError, ValueError, RuntimeError) as error:
        print(f"离线知识操作失败（{type(error).__name__}）：{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
