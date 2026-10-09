"""Agent 组合层。

用途：组装模型、显式工具、运行器与对话适配。
边界：不执行请求、不自动注册工具、不访问数据库。
"""

from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from odmflow.after_sales.application import AfterSalesReadService
from odmflow.after_sales.repository import SqlAfterSalesRepository
from odmflow.configuration import ApplicationSettings, RagSettings
from odmflow.conversations import ConversationService
from odmflow.conversations.context_contracts import ContextRequest
from odmflow.conversations.context_repository import SqlConversationContextRepository
from odmflow.orders.application import OrderReadService
from odmflow.orders.repository import SqlOrderRepository
from odmflow.profiles import ProfileService

from .approvals.service import ApprovalService
from .configuration import AgentTimeoutSettings, RagRuntimeSettings
from .execution.runner import LangGraphAgentRunner
from .integrations.action_gateway import BoundActionGateway
from .integrations.after_sales_gateway import BoundAfterSalesGateway
from .integrations.context_gateway import ThreadedContextGateway
from .integrations.conversation_gateway import ThreadedConversationGateway
from .integrations.knowledge_gateway import ThreadedKnowledgeGateway
from .integrations.model_provider import build_chat_model
from .integrations.order_gateway import BoundOrderReadGateway
from .integrations.profile_gateway import ThreadedProfileGateway
from .memory.configuration import ContextSettings
from .memory.profile_configuration import ProfileSettings
from .ports import (
    AgentAfterSalesPort,
    AgentApplicationPort,
    AgentContextPort,
    AgentKnowledgePort,
    AgentOrderReadPort,
    AgentProfilePort,
    AgentRunner,
)
from .tasks.configuration import TaskSettings
from .tools.catalog import build_capability_catalog
from .turn_service import AgentTurnService


def build_agent_runner(settings: ApplicationSettings) -> AgentRunner | None:
    """构造现行 runner，未填写模型配置时保持禁用。

    Args:
        settings: 启动时读取的完整应用快照；本函数不重复读文件或策略环境变量。
    Returns:
        可流式执行的 runner，或 None。
    Raises:
        ValueError: 模型端点或等待预算配置无效。
    """
    timeouts = AgentTimeoutSettings(
        settings.model.request_timeout_seconds, settings.agent.turn_timeout_seconds
    )
    model = build_chat_model(timeouts)
    if model is None:
        return None
    return LangGraphAgentRunner(
        model,
        build_capability_catalog(),
        timeout_seconds=timeouts.turn_seconds,
        context_settings=ContextSettings(
            enabled=settings.memory.conversation.enabled,
            window_tokens=settings.memory.conversation.window_tokens,
            output_tokens=settings.memory.conversation.output_tokens,
            keep_messages=settings.memory.conversation.keep_messages,
            trigger_messages=settings.memory.conversation.trigger_messages,
            summary_tokens=settings.memory.conversation.summary_tokens,
            summary_timeout=settings.memory.conversation.summary_timeout_seconds,
            max_batches=settings.memory.conversation.max_batches,
            page_messages=settings.memory.conversation.page_messages,
        ),
        profile_settings=ProfileSettings(
            settings.memory.profile.enabled, settings.memory.profile.timeout_seconds
        ),
        task_settings=TaskSettings(
            max_tasks=settings.agent.tasks.max_tasks,
            max_capability_calls=settings.agent.tasks.max_capability_calls,
            max_model_calls=settings.agent.tasks.max_model_calls,
            max_replans=settings.agent.tasks.max_replans,
            max_argument_repairs=settings.agent.tasks.max_argument_repairs,
            order_read_retry_enabled=settings.orders.read.retry_enabled,
        ),
    )


def build_turn_service(
    runner: AgentRunner,
    conversations: ConversationService,
    knowledge: AgentKnowledgePort | None = None,
    context_store: AgentContextPort | None = None,
    profile_store: AgentProfilePort | None = None,
    order_reader_factory: Callable[[str], AgentOrderReadPort] | None = None,
    action_factory: Callable[[ContextRequest], AgentApplicationPort] | None = None,
    after_sales_factory: Callable[[str], AgentAfterSalesPort] | None = None,
) -> AgentTurnService:
    """组合整轮应用服务。

    Args:
        runner: 真实或替身流式运行器。
        conversations: 同步对话公共服务。
        knowledge: 可选的本轮知识查询端口。
        context_store: 可选的同会话派生摘要端口，默认不做额外存储读取。
        profile_store: 可选的本人结构化画像端口，不提供模型任意写入工具。
        order_reader_factory: 用可信owner构造本人只读端口，不接受模型身份参数。
    Returns:
        使用线程池存储适配的应用用例。
    """
    return AgentTurnService(
        runner,
        ThreadedConversationGateway(conversations),
        knowledge,
        context_store=context_store,
        profile_store=profile_store,
        order_reader_factory=order_reader_factory,
        action_factory=action_factory,
        after_sales_factory=after_sales_factory,
    )


def build_chat_knowledge(policy: RagSettings) -> ThreadedKnowledgeGateway:
    """使用已加载的RAG策略；懒导入重依赖并一次核验模型/索引。

    Args:
        policy: 启动快照的RAG分组，不读取旧策略环境变量。
    Returns:
        使用共享检索策略和在线预算的线程网关。
    Raises:
        KnowledgeError: 本机资源/索引未就绪。
    """
    from odmflow.knowledge.bootstrap import build_knowledge_service
    from odmflow.knowledge.configuration import KnowledgeSettings
    from odmflow.knowledge.domain import KnowledgeError

    budget = RagRuntimeSettings(
        policy.timeout_seconds, policy.top_k, policy.max_context_chars, policy.max_distance
    )
    cutoff = budget.max_distance
    settings = KnowledgeSettings.from_environment(policy)
    if cutoff is not None and settings.retrieval_mode != "vector":
        raise KnowledgeError("距离阈值仅支持向量模式，请移除rag.max_distance")
    service = build_knowledge_service(settings)
    service.initialize_query()
    return ThreadedKnowledgeGateway(
        service,
        timeout=budget.timeout_seconds,
        top_k=budget.top_k,
        max_chars=budget.max_context_chars,
        max_distance=cutoff,
    )


def build_context_store(session_factory: sessionmaker[Session] | None) -> AgentContextPort | None:
    """经组合层构造摘要存储适配，不在main暴露具体线程网关。

    Args:
        session_factory: 同会话SQL短事务工厂，无配置时为None。
    Returns:
        摘要异步端口；构造不查询数据库。
    """
    return (
        ThreadedContextGateway(SqlConversationContextRepository(session_factory))
        if session_factory is not None
        else None
    )


def build_profile_store(service: ProfileService | None) -> AgentProfilePort | None:
    """将已有画像服务组合为线程池端口；缺项时不自动建表或查询。"""
    return ThreadedProfileGateway(service) if service is not None else None


def build_order_reader_factory(
    sessions: sessionmaker[Session] | None,
) -> Callable[[str], AgentOrderReadPort] | None:
    """构造本人绑定工厂；构造时不查询数据库或生成订单。

    Args:
        sessions: 现有短事务会话工厂；无配置时为None。
    Returns:
        只由服务器用可信owner调用的工厂，或未配置时None。
    """
    if sessions is None:
        return None
    service = OrderReadService(SqlOrderRepository(sessions))
    return lambda owner_id: BoundOrderReadGateway(service, owner_id)


def build_action_factory(
    service: ApprovalService | None,
) -> Callable[[ContextRequest], AgentApplicationPort] | None:
    """将每轮可信来源绑定准备端口，不向模型传owner/会话/图ID。"""
    if service is None:
        return None
    return lambda source: BoundActionGateway(
        service, source.owner_id, source.conversation_id, source.turn_id
    )


def build_after_sales_factory(
    sessions: sessionmaker[Session] | None,
) -> Callable[[str], AgentAfterSalesPort] | None:
    """构造本人只读端口工厂，不在启动时访问数据库。"""
    if sessions is None:
        return None
    service = AfterSalesReadService(SqlAfterSalesRepository(sessions))
    return lambda owner: BoundAfterSalesGateway(service, owner)
