"""用途：知识能力输入和直接执行适配。边界：生命周期复用RagSearchService，不创建索引或伪造ToolRuntime。"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ..run_context import AgentRunContext
from ..tasks.contracts import AgentTask, TaskResult
from .rag.service import RagSearchService


class KnowledgeSearchInput(BaseModel):
    """模型只提供问题，不允许身份、资源路径、TopK或额外控制参数。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    query: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
    ] = Field(description="根据本轮完整需求和明确历史构造问题，勿猜测条件")


async def execute_knowledge(task: AgentTask, context: AgentRunContext) -> TaskResult:
    """复用真实检索及先存后发机制，结果仅作为资料供汇总。"""
    payload = KnowledgeSearchInput.model_validate(task.arguments)
    text = await RagSearchService().execute(
        payload.query, context, context.emit or (lambda event: None)
    )
    sources = (
        tuple(source.source_id for source in context.rag_evidence.sources)
        if context.rag_evidence
        else ()
    )
    return TaskResult(task.task_id, "ok", text, sources=sources)
