"""用途：本人画像HTTP读改删；边界：复用身份/Origin/CSRF，不接收自报用户ID，不执行SQL或LLM。"""

from typing import Annotated, Self

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from odmflow.identity.dependencies import (
    get_authenticated_principal,
    get_authorized_write_principal,
)
from odmflow.identity.domain import AuthenticatedPrincipal

from .application import ProfileService
from .domain import (
    ProfileConflict,
    ProfileField,
    ProfileSnapshot,
    ProfileUnavailable,
    normalize_profile_value,
)

router = APIRouter(prefix="/memory/profile", tags=["memory-profile"])


class ProfileRevisionRequest(BaseModel):
    """修改前的全用户版本，禁止传入身份或宽松布尔版本。"""

    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0, strict=True)


class ProfileEditRequest(ProfileRevisionRequest):
    """手动设置一个允许字段；值域与应用层共用。"""

    field_key: ProfileField
    value: str

    @model_validator(mode="after")
    def normalize_value(self) -> Self:
        """在HTTP边界把非法值转换为422，不写库。"""
        self.value = normalize_profile_value(self.field_key, self.value)
        return self


def _service(request: Request) -> ProfileService:
    """取组合根服务，不可用时返回503。"""
    service: ProfileService | None = request.app.state.profile_service
    if service is None:
        raise HTTPException(status_code=503, detail="Profile storage unavailable")
    return service


@router.get("")
def read_profile(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authenticated_principal)],
) -> ProfileSnapshot:
    """返回本人字段、删除状态和来源；不由路径选择账号。"""
    try:
        return _service(request).read(principal.user_id)
    except ProfileUnavailable as error:
        raise HTTPException(status_code=503, detail="Profile storage unavailable") from error


@router.patch("")
def edit_profile(
    payload: ProfileEditRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authorized_write_principal)],
) -> ProfileSnapshot:
    """版本一致才更新手动字段，失败不无声覆盖。"""
    try:
        return _service(request).edit(
            principal.user_id, payload.revision, payload.field_key, payload.value
        )
    except ProfileConflict as error:
        raise HTTPException(status_code=409, detail="Profile revision changed") from error
    except ProfileUnavailable as error:
        raise HTTPException(status_code=503, detail="Profile storage unavailable") from error


@router.delete("/{field_key}")
def delete_profile(
    field_key: ProfileField,
    payload: ProfileRevisionRequest,
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_authorized_write_principal)],
) -> ProfileSnapshot:
    """删除一个字段并抑制自动回填，不删除原聊天。"""
    try:
        return _service(request).delete(principal.user_id, payload.revision, field_key)
    except ProfileConflict as error:
        raise HTTPException(status_code=409, detail="Profile revision changed") from error
    except ProfileUnavailable as error:
        raise HTTPException(status_code=503, detail="Profile storage unavailable") from error
