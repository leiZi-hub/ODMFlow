"""协调画像读取、候选提取和受控保存；不写SQL、不决定HTTP或运行主图。"""

import json
from collections.abc import AsyncGenerator, Awaitable, Callable

from odmflow.profiles.domain import ProfileCandidate, ProfileSnapshot, ProfileSource

from ..contracts import AgentStreamEvent
from ..run_context import AgentRunContext
from ..tracing.operations import (
    OperationDescriptor,
    OperationKind,
    OperationName,
    OperationStatus,
    ToolDetails,
)
from .profile_configuration import ProfileSettings


def has_profile_signal(message: str) -> bool:
    """只筛选可能的持续偏好/自述以限制费用，不代替模型语义判断。"""
    return any(
        marker in message.lower()
        for marker in (
            "以后",
            "默认",
            "习惯",
            "一直",
            "通常",
            "我负责",
            "我的工作",
            "我是",
            "喜欢",
            "偏好",
            "prefer",
            "always",
            "usually",
            "from now",
            "i work",
            "my role",
        )
    )


class ProfilePreparation:
    """请求级画像准备；失败保留已读取的有效画像并让主回答继续。"""

    def __init__(
        self,
        settings: ProfileSettings,
        extract: Callable[[tuple[ProfileSource, ...]], Awaitable[tuple[ProfileCandidate, ...]]],
    ) -> None:
        """注入策略和候选提取适配，不执行模型或存储。"""
        self._settings, self._extract = settings, extract
        self.notice = ""

    async def events(
        self, message: str, context: AgentRunContext, *, summarized: bool
    ) -> AsyncGenerator[AgentStreamEvent]:
        """加载可信当前账号画像，按成本门禁最多提取一次并记录实际结果。

        Args:
            message: 当前用户原文，仅用于候选成本预筛。
            context: 服务端创建的账号、轮边界与画像端口。
            summarized: 本轮确实完成了同会话摘要，不是单纯达到阈值。
        Yields:
            已保存的画像准备开始、结束事件；关闭时没有事件。
        """
        if (
            not self._settings.enabled
            or context.profile_store is None
            or context.context_request is None
        ):
            return
        attempted = summarized or has_profile_signal(message)
        details = ToolDetails(
            json.dumps(
                {
                    "extraction_requested": attempted,
                    "reason": "summary" if summarized else "signal" if attempted else "load_only",
                }
            )
        )
        operation = await context.operations.start(
            OperationDescriptor(OperationKind.CONTEXT, OperationName.PREPARE_PROFILE), details
        )
        yield AgentStreamEvent("operation_started", operation=operation)
        profile = ProfileSnapshot(0, ())
        error_code = None
        saved_fields: list[str] = []
        try:
            snapshot = await context.profile_store.load_sources(context.context_request, 8)
            profile = snapshot.profile
            context.profile_values = profile.active_values()
            if attempted:
                candidates = await self._extract(snapshot.sources)
                if candidates:
                    updated = await context.profile_store.apply_candidates(
                        context.context_request, snapshot, candidates
                    )
                    before = dict(profile.active_values())
                    saved_fields = [
                        key for key, value in updated.active_values() if before.get(key) != value
                    ]
                    profile = updated
                    context.profile_values = profile.active_values()
        except Exception as error:
            # 不记录SDK原始异常/原话；操作结果公开降级原因，主图继续。
            error_code = type(error).__name__
            self.notice = "用户偏好暂未完成更新，本轮将继续回答。\n\n"
        result = {
            "loaded_fields": [key for key, _ in context.profile_values],
            "saved_fields": saved_fields,
            "revision": profile.revision,
            "extraction_requested": attempted,
        }
        finished = await context.operations.finish(
            operation.id,
            OperationStatus.FAILED if error_code else OperationStatus.COMPLETED,
            ToolDetails(
                details.arguments_json,
                json.dumps(result, ensure_ascii=False),
                error_code=error_code,
            ),
        )
        yield AgentStreamEvent("operation_finished", operation=finished)
