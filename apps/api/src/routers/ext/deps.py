"""教学工具（ext）共用的依赖。

本目录是部署方（先进智造学堂 / SYSU-SAM）新增的，上游没有，因此不需要
`/* --- SYSU-SAM --- */` 之类的注释块——整个 `src/routers/ext/` 都是我们的代码。

这里只放**所有 ext 子路由都能用**的东西。单个工具自己的依赖放在自己的
子模块里，不要往这里塞。
"""

from typing import Optional

from fastapi import Depends, HTTPException, Query, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import AnonymousUser, PublicUser
from src.security.auth import get_current_user
from src.security.org_auth import get_user_org_role, require_org_role_permission


async def verify_teacher(
    user: PublicUser,
    org_id: int,
    db_session: AsyncSession,
) -> None:
    """组织级第一道门：调用者必须是该组织的 Admin / Maintainer / Instructor。

    实现上就是检查角色 rights 里的 ``dashboard.action_access``。这不是近似，
    而是精确等价：`src/services/setup/setup.py` 里四个内置全局角色中，
    Admin(1) / Maintainer(2) / Instructor(3) 的 ``dashboard.action_access``
    为 True，User(4) 为 False。超级管理员由 ``require_org_role_permission``
    内部直接放行。

    前端的判断口径与此一致：`useAdminStatus().isAdmin` 读的就是
    ``rights.dashboard.action_access``，所以前端能看到「教学工具」菜单的人，
    正好是这里能通过的人。

    注意这只是**组织级**的门。涉及具体课程的工具还要再按课程权限收窄，
    见 `docs/sysu-sam/EXT_TOOLS.md`。
    """
    if isinstance(user, AnonymousUser) or getattr(user, "id", 0) in (0, None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    await require_org_role_permission(
        user.id,
        org_id,
        db_session,
        "dashboard",
        "action_access",
    )


async def require_teacher(
    request: Request,
    org_id: int = Query(..., description="组织 id，权限按该组织内的角色判定"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> PublicUser:
    """FastAPI 依赖版本：教学工具接口的标准写法。

    用法::

        @router.get("/xxx")
        async def api_xxx(
            *,
            current_user: PublicUser = Depends(require_teacher),
            db_session: AsyncSession = Depends(get_db_session),
            org_id: int,
        ):
            ...

    因为它把 ``org_id`` 声明成 query 参数，**挂了这个依赖的接口，调用方必须带
    ``?org_id=<id>``**。前端 `useOrg()` 里就有 `org.id`，拼上即可。

    不通过时抛 403（匿名调用者抛 401）。
    """
    await verify_teacher(current_user, org_id, db_session)
    return current_user


async def current_org_role_name(
    user: PublicUser,
    org_id: int,
    db_session: AsyncSession,
) -> Optional[str]:
    """当前用户在该组织里的角色名，超管或非成员返回 None。

    只用于展示（例如 `/ext/health` 回显身份），不要拿它做权限判断。
    """
    user_id = getattr(user, "id", None)
    if not user_id:
        return None
    role = await get_user_org_role(user_id, org_id, db_session)
    return role.name if role else None
