"""`GET /ext/health` —— 教学工具扩展的自检接口。

前端的「示例工具」页面调它，用来证明前后端扩展点是通的：菜单能进、路由能到、
鉴权能过、数据能回。其他工具不要依赖它的返回结构。
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import PublicUser
from src.routers.ext import enabled_tools
from src.routers.ext.deps import current_org_role_name, require_teacher

router = APIRouter()

# 与 apps/api/pyproject.toml 的 version 对齐；扩展层自己的版本另算。
EXT_VERSION = "1.0.0"


class ExtHealthRead(BaseModel):
    """`/ext/health` 的返回体。"""

    status: str
    ext_version: str
    org_id: int
    user_id: int
    username: str
    role: Optional[str]
    tools: list[str]


@router.get(
    "/health",
    response_model=ExtHealthRead,
    tags=["ext"],
    summary="Teaching tools extension health check",
    description=(
        "Returns the extension layer version, the caller's identity and role "
        "within the given organization, and the list of mounted ext tools. "
        "Requires an Admin / Maintainer / Instructor role in that organization."
    ),
    responses={
        200: {"description": "Extension layer is reachable.", "model": ExtHealthRead},
        401: {"description": "Authentication required"},
        403: {"description": "User is not a teacher in this organization"},
    },
)
async def api_ext_health(
    *,
    org_id: int,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
) -> ExtHealthRead:
    role = await current_org_role_name(current_user, org_id, db_session)
    return ExtHealthRead(
        status="ok",
        ext_version=EXT_VERSION,
        org_id=org_id,
        user_id=current_user.id,
        username=current_user.username,
        role=role,
        tools=enabled_tools(),
    )
