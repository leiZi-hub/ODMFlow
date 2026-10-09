"""显式 LangGraph 运行适配。

用途：运行框架图并把模型片段／实际工具结果转为内部事件。
边界：不决定 HTTP、存储和业务规则；工具由组合层注入。
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import aclosing
from functools import partial
from time import perf_counter
from typing import Any, cast

from langchain_core.language_models.chat_models import BaseChatModel

from ..configuration import DEFAULT_AGENT_TIMEOUT_SECONDS
from ..contracts import AgentStreamEvent, EmptyAgentReply, QueryCompactionFailed
from ..memory.configuration import ContextSettings
from ..memory.coordinator import ContextPreparation
from ..memory.messages import build_model_messages
from ..memory.profile_configuration import ProfileSettings
from ..memory.profile_extraction import extract_profile
from ..memory.profile_preparation import ProfilePreparation
from ..memory.summarizer import build_summary_signature, summarize_history
from ..run_context import AgentRunContext
from ..tasks.budget import TaskBudget, TaskLimitExceeded
from ..tasks.configuration import TaskSettings
from ..tasks.contracts import ArgumentEvidence, Capability
from ..tools.contracts import CapabilityDefinition
from ..tools.rag.query_compaction import compact_query
from .graph_factory import build_agent_graph
from .stream_decoder import GraphStreamDecoder


class LangGraphAgentRunner:
    """运行有限任务图，正文与已保存的操作事件分离输出。"""

    def __init__(
        self,
        model: BaseChatModel,
        catalog: Mapping[Capability, CapabilityDefinition],
        timeout_seconds: float = DEFAULT_AGENT_TIMEOUT_SECONDS,
        context_settings: ContextSettings | None = None,
        profile_settings: ProfileSettings | None = None,
        task_settings: TaskSettings | None = None,
    ) -> None:
        """注入模型、显式工具集合与超时，构造受限的 Agent 图。

        Args:
            model: 聊天模型适配器；构造图不执行请求。
            catalog: 组合层明确允许的能力目录。
            timeout_seconds: 每轮总时限，包含模型与工具循环。
            context_settings: 同会话摘要与逐次模型预算；缺省采用保守本地配置。
            profile_settings: 用户画像准备策略；关闭时不读取、提取或注入。
            task_settings: 任务、模型、能力、修正及只读重试的硬上限。
        Returns:
            无；初始化运行器。
        """

        self.timeout_seconds = timeout_seconds
        self.model = model
        self.context_settings = context_settings or ContextSettings()
        self.profile_settings = profile_settings or ProfileSettings()
        self.summary_signature = build_summary_signature(model, self.context_settings)
        self.task_settings = task_settings or TaskSettings()
        self._graph = build_agent_graph(model, catalog, self.context_settings, self.task_settings)

    async def stream(
        self,
        message: str,
        history: list[tuple[str, str]],
        *,
        context: AgentRunContext,
    ) -> AsyncIterator[AgentStreamEvent]:
        """实际消费 LangGraph 图流，仅将回答节点片段和已保存事件产出。

        Args:
            message: 当前用户消息。
            history: 存储不可用或关闭摘要时的升序完整窗口；有摘要端口则重新准备。
            context: 本轮独立的存储/知识端口、可信轮边界及证据，不进入模型参数。
        Yields:
            token、已保存的真实操作生命周期和完整回复 done 事件。
        Raises:
            TimeoutError: 超出每轮总时限。
            EmptyAgentReply: 图结束但没有最终回复。
            Exception: 模型、框架或工具限额异常，由应用层决定保底。
        """

        context.budget = TaskBudget(self.task_settings)
        context.deadline = perf_counter() + self.timeout_seconds
        context.argument_evidence = ArgumentEvidence(
            tuple(text for role, text in history if role == "user") + (message,)
        )

        async def compact(query: str) -> str:
            try:
                context.budget.consume_model()
            except TaskLimitExceeded:
                raise QueryCompactionFailed("query_compaction_budget_exhausted") from None
            return await compact_query(
                self.model,
                query,
                user_message=message,
                context=context,
                settings=self.context_settings,
            )

        context.compact_query = compact
        preparation = ContextPreparation(
            history,
            self.context_settings,
            self.summary_signature,
            partial(summarize_history, self.model, self.context_settings),
        )
        decoder = GraphStreamDecoder()
        profiles = ProfilePreparation(
            self.profile_settings, partial(extract_profile, self.model, self.profile_settings)
        )
        async with asyncio.timeout(self.timeout_seconds):
            async with aclosing(preparation.events(message, context)) as events:
                async for event in events:
                    yield event
            prepared = preparation.prepared
            async with aclosing(
                profiles.events(message, context, summarized=bool(prepared.batches))
            ) as events:
                async for event in events:
                    yield event
            if profiles.notice:
                yield AgentStreamEvent("token", text=profiles.notice)
            if prepared.notice:
                yield AgentStreamEvent("token", text=prepared.notice)
            # 已安装框架返回带aclose的异步生成器，SDK标注仅为AsyncIterator。
            # 在具体框架边界补足关闭协议，不把cast扩散到应用用例。
            graph_stream = cast(
                AsyncGenerator[tuple[str, Any]],
                self._graph.astream(
                    {"messages": build_model_messages(prepared, message, context.profile_values)},
                    config={"recursion_limit": 32},
                    stream_mode=["messages", "updates", "custom"],
                    context=context,
                ),
            )
            # 上层停止消费时显式关闭图；不等待GC终结。
            async with aclosing(graph_stream):
                async for mode, update in graph_stream:
                    for event in decoder.consume(mode, update):
                        yield event
        if not decoder.final_reply:
            raise EmptyAgentReply
        yield AgentStreamEvent(
            "done",
            text=profiles.notice
            + preparation.prepared.notice
            + context.budget_notice
            + decoder.final_reply,
        )
