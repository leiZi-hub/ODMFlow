"""ODMFlow 应用组合入口。

用途：
    创建 FastAPI 应用并挂载各功能模块公开的路由。

边界：
    不承载领域规则、业务用例或基础设施实现。
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from odmflow.agent import AgentRunner
from odmflow.agent.action_api import router as action_router
from odmflow.agent.api import router as agent_router
from odmflow.agent.approvals.bootstrap import build_approval_service
from odmflow.agent.bootstrap import (
    build_action_factory,
    build_after_sales_factory,
    build_agent_runner,
    build_chat_knowledge,
    build_context_store,
    build_order_reader_factory,
    build_profile_store,
    build_turn_service,
)
from odmflow.agent.configuration import AgentTimeoutSettings
from odmflow.agent.integrations.knowledge_gateway import (
    ThreadedKnowledgeGateway,
    UnavailableKnowledgeGateway,
)
from odmflow.agent.ports import AgentKnowledgePort
from odmflow.configuration import ApplicationSettings, load_application_settings
from odmflow.conversations import ConversationService, ConversationStorageUnavailable
from odmflow.conversations.api import router as conversations_router
from odmflow.conversations.repository import SqlConversationRepository
from odmflow.identity import router as identity_router
from odmflow.identity.bootstrap import build_auth_service
from odmflow.persistence import build_database_sessions
from odmflow.profiles import ProfileService
from odmflow.profiles.api import router as profile_router
from odmflow.profiles.repository import SqlProfileRepository
from odmflow.system import router as system_router

logger = logging.getLogger(__name__)


def create_app(
    session_factory: sessionmaker[Session] | None = None,
    agent_service: AgentRunner | None = None,
    knowledge: AgentKnowledgePort | None = None,
    *,
    settings: ApplicationSettings | None = None,
) -> FastAPI:
    """创建并组装一个 ODMFlow FastAPI 应用实例。

    Args:
        session_factory: 测试时可注入隔离的身份数据库会话工厂。
        agent_service: 测试时可注入假模型 Agent；缺省时从环境创建。
        knowledge: 可注入隔离知识端口。
        settings: 完整应用策略快照；缺省只加载一次实际TOML，错误时拒绝启动。

    Returns:
        已注册系统、身份、Agent 流式入口与对话查询路由的 FastAPI 应用。
    """

    policy = settings if settings is not None else load_application_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """只在启用时初始化一次本地知识；失败不影响登录及消息查询。"""
        online = knowledge
        if online is None and policy.rag.enabled:
            try:
                online = await asyncio.to_thread(build_chat_knowledge, policy.rag)
            except Exception as error:
                logger.warning("Knowledge startup failed: %s", type(error).__name__)
                online = UnavailableKnowledgeGateway()
        if (
            online is not None
            and app.state.agent_service is not None
            and app.state.conversation_service is not None
        ):
            app.state.agent_turn_service = build_turn_service(
                app.state.agent_service,
                app.state.conversation_service,
                online,
                app.state.context_store,
                app.state.profile_store,
                app.state.order_reader_factory,
                app.state.action_factory,
                app.state.after_sales_factory,
            )
        yield
        if isinstance(online, ThreadedKnowledgeGateway):
            await online.close()
        if app.state.approval_service is not None:
            await app.state.approval_service.close()

    application = FastAPI(title="ODMFlow", version="0.1.0", lifespan=lifespan)
    application.state.application_settings = policy
    # 开关只决定本人执行详情的可见性，不改变登录与对话归属校验。
    application.state.trace_debug_enabled = (
        os.getenv("ODMFLOW_TRACE_DEBUG_ENABLED", "false").strip().lower() == "true"
    )

    @application.exception_handler(SQLAlchemyError)
    @application.exception_handler(ConversationStorageUnavailable)
    async def database_error(_request: Request, error: Exception) -> JSONResponse:
        """记录数据库异常并向调用方返回不泄露连接细节的错误。"""

        logger.error("Authentication storage operation failed", exc_info=error)
        return JSONResponse(
            status_code=503, content={"detail": "Authentication storage unavailable"}
        )

    agent_timeouts = AgentTimeoutSettings(
        policy.model.request_timeout_seconds, policy.agent.turn_timeout_seconds
    )
    if session_factory is None:
        session_factory = build_database_sessions()
    application.state.auth_service = build_auth_service(session_factory)
    application.state.profile_service = (
        ProfileService(SqlProfileRepository(session_factory))
        if session_factory is not None
        else None
    )
    application.state.context_store = build_context_store(session_factory)
    application.state.order_reader_factory = build_order_reader_factory(session_factory)
    application.state.approval_service = build_approval_service(session_factory, policy.approvals)
    application.state.action_factory = build_action_factory(application.state.approval_service)
    application.state.after_sales_factory = build_after_sales_factory(session_factory)
    application.state.profile_store = build_profile_store(application.state.profile_service)
    application.state.conversation_service = (
        ConversationService(
            SqlConversationRepository(session_factory), stale_after=agent_timeouts.recovery_after()
        )
        if session_factory is not None
        else None
    )
    application.state.agent_service = (
        agent_service if agent_service is not None else build_agent_runner(policy)
    )
    application.state.agent_turn_service = (
        build_turn_service(
            application.state.agent_service,
            application.state.conversation_service,
            knowledge,
            application.state.context_store,
            application.state.profile_store,
            application.state.order_reader_factory,
            application.state.action_factory,
            application.state.after_sales_factory,
        )
        if application.state.agent_service is not None
        and application.state.conversation_service is not None
        else None
    )
    application.include_router(system_router)
    application.include_router(identity_router)
    application.include_router(agent_router)
    application.include_router(action_router)
    application.include_router(conversations_router)
    application.include_router(profile_router)
    return application


app = create_app()
