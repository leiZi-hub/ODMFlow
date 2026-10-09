"""用途：将执行异常映射为现行安全保底文案。边界：不吞取消、不返回SDK原文、不写SQL。"""

import logging

from odmflow.conversations import ConversationStorageUnavailable
from odmflow.knowledge.domain import KnowledgeError
from odmflow.orders.domain import OrderReadUnavailable

from .contracts import ContextBudgetExceeded, QueryCompactionFailed

logger = logging.getLogger(__name__)

_FAILURE_REPLIES: tuple[tuple[type[Exception], str], ...] = (
    (
        OrderReadUnavailable,
        "订单查询暂时不可用，本轮未取得可核实的订单结果。请稍后发送新的消息继续。",
    ),
    (
        ContextBudgetExceeded,
        "本轮问题或工具资料超过可用上下文预算，未继续生成回复。请拆分问题后再发送。",
    ),
    (
        QueryCompactionFailed,
        "暂时无法整理出可检索的问题，本轮未完成资料查询。请将需求拆分成几个问题再咨询。",
    ),
    (
        KnowledgeError,
        "知识查询不可用或问题超过向量模型长度限制，本轮未生成企业答案。请缩短问题或检查知识索引。",
    ),
    (ConversationStorageUnavailable, "操作记录保存失败，本轮未继续执行。请稍后发送新的消息。"),
    (TimeoutError, "模型响应超时，本轮回复未完成。请发送新的消息继续。"),
)


def failure_reply(error: Exception) -> str:
    """按具体类型优先匹配保底，未知异常只记录类型。

    Args:
        error: 执行异常；取消必须在调用方单独传播。
    Returns:
        不泄漏模型、连接和凭证细节的现行文案。
    """
    for error_type, reply in _FAILURE_REPLIES:
        if isinstance(error, error_type):
            return reply
    logger.warning("Conversation model run failed: %s", type(error).__name__)
    return "模型运行失败，本轮回复未完成。请发送新的消息继续。"
