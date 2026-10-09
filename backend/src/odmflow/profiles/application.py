"""用途：提供画像读改删和受控自动候选应用入口。边界：不依赖HTTP/SQL/LLM，不决定提取时机。"""

from typing import Protocol

from odmflow.conversations.context_contracts import ContextRequest

from .domain import (
    ProfileCandidate,
    ProfileField,
    ProfileInputSnapshot,
    ProfileSnapshot,
    normalize_profile_value,
)


class ProfileRepository(Protocol):
    """应用所需短事务契约，真实SQL实现由组合根注入。"""

    def read(self, owner: str) -> ProfileSnapshot:
        """返回本人全部允许字段和当前版本。"""
        ...

    def change(self, owner: str, revision: int, key: str, value: str | None) -> ProfileSnapshot:
        """按版本保存手动值或删除墓碑。"""
        ...

    def load_sources(self, request: ContextRequest, limit: int) -> ProfileInputSnapshot:
        """读取真实轮次边界内的用户原文及全用户版本。"""
        ...

    def apply_candidates(
        self,
        request: ContextRequest,
        snapshot: ProfileInputSnapshot,
        candidates: tuple[ProfileCandidate, ...],
    ) -> ProfileSnapshot:
        """核验原文、归属及CAS后原子提交有资格的候选。"""
        ...


class ProfileService:
    """画像公共用例；HTTP与自动提取共用规则，不提供任意字段写工具。"""

    def __init__(self, repository: ProfileRepository) -> None:
        """注入存储，不查询数据库。"""
        self._repository = repository

    def read(self, owner: str) -> ProfileSnapshot:
        """读取可信主体的字段；owner由调用层验证，不由模型提供。"""
        return self._repository.read(owner)

    def edit(self, owner: str, revision: int, key: str, value: str) -> ProfileSnapshot:
        """校验后保存手动字段；版本冲突抛ProfileConflict。"""
        return self._repository.change(owner, revision, key, normalize_profile_value(key, value))

    def delete(self, owner: str, revision: int, key: str) -> ProfileSnapshot:
        """删除并抑制自动回填；不删除原聊天或会话摘要。"""
        ProfileField(key)
        return self._repository.change(owner, revision, key, None)

    def load_sources(self, request: ContextRequest, limit: int) -> ProfileInputSnapshot:
        """加载1–8条同会话原文；越界limit不进入存储。"""
        if not 1 <= limit <= 8:
            raise ValueError("画像原文页必须为1–8条")
        return self._repository.load_sources(request, limit)

    def apply_candidates(
        self,
        request: ContextRequest,
        snapshot: ProfileInputSnapshot,
        candidates: tuple[ProfileCandidate, ...],
    ) -> ProfileSnapshot:
        """重新校验模型外部数据并要求整个批次来源有效；失败不部分写入。"""
        validated = tuple(ProfileCandidate.model_validate(x.model_dump()) for x in candidates)
        return self._repository.apply_candidates(request, snapshot, validated)
