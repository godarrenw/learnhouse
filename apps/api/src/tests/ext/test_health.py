"""教学工具扩展骨架的测试。

覆盖两件事：
1. `require_teacher` / `verify_teacher` 的权限口径 —— Admin / Maintainer /
   Instructor 放行，普通 User 403，跨组织 403。这是其他工具都要复用的那道门，
   所以这里把口径钉死。
2. `/ext/health` 的挂载与返回体。
"""

from datetime import datetime

import pytest
from fastapi import HTTPException

from src.db.roles import Role, RoleTypeEnum
from src.db.user_organizations import UserOrganization
from src.db.users import AnonymousUser, PublicUser, User
from src.routers.ext import SUBMODULES, enabled_tools, include_all
from src.routers.ext.deps import current_org_role_name, verify_teacher
from src.tests.conftest import ADMIN_RIGHTS


def _rights_with_dashboard(access: bool) -> dict:
    """基于 ADMIN_RIGHTS 造一份只改 dashboard.action_access 的 rights。"""
    rights = ADMIN_RIGHTS.model_dump()
    rights["dashboard"] = {"action_access": access}
    return rights


async def _make_user_with_role(
    db, org, *, user_id: int, role_id: int, role_name: str, dashboard_access: bool
) -> PublicUser:
    """在 org 里造一个带指定 dashboard 权限的用户。"""
    role = Role(
        id=role_id,
        name=role_name,
        org_id=org.id,
        role_type=RoleTypeEnum.TYPE_ORGANIZATION,
        role_uuid=f"role_{role_name.lower()}",
        rights=_rights_with_dashboard(dashboard_access),
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(role)
    await db.commit()

    user = User(
        id=user_id,
        username=role_name.lower(),
        first_name=role_name,
        last_name="Tester",
        email=f"{role_name.lower()}@test.com",
        password="hashed_password",
        user_uuid=f"user_{role_name.lower()}",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    db.add(
        UserOrganization(
            user_id=user.id,
            org_id=org.id,
            role_id=role.id,
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
    )
    await db.commit()

    return PublicUser(
        id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        user_uuid=user.user_uuid,
    )


class TestVerifyTeacher:
    """`verify_teacher` 就是教学工具的组织级第一道门。"""

    async def test_admin_passes(self, db, org, admin_user):
        # 不抛异常即通过
        await verify_teacher(admin_user, org.id, db)

    async def test_instructor_passes(self, db, org):
        """Instructor（内置角色 id=3）的 dashboard.action_access 是 True。

        这是本依赖最需要证明的用例：教学工具要对讲师开放，而讲师既不是
        Admin 也不是 Maintainer，靠角色 id 判断的写法会把他挡在门外。
        """
        instructor = await _make_user_with_role(
            db, org, user_id=31, role_id=3, role_name="Instructor", dashboard_access=True
        )
        await verify_teacher(instructor, org.id, db)

    async def test_maintainer_passes(self, db, org):
        maintainer = await _make_user_with_role(
            db, org, user_id=32, role_id=2, role_name="Maintainer", dashboard_access=True
        )
        await verify_teacher(maintainer, org.id, db)

    async def test_regular_user_forbidden(self, db, org, regular_user):
        with pytest.raises(HTTPException) as exc:
            await verify_teacher(regular_user, org.id, db)
        assert exc.value.status_code == 403

    async def test_other_org_forbidden(self, db, org, other_org, admin_user):
        """在 A 组织是管理员，不代表能碰 B 组织的教学工具。"""
        with pytest.raises(HTTPException) as exc:
            await verify_teacher(admin_user, other_org.id, db)
        assert exc.value.status_code == 403

    async def test_anonymous_unauthorized(self, db, org):
        with pytest.raises(HTTPException) as exc:
            await verify_teacher(AnonymousUser(), org.id, db)  # type: ignore[arg-type]
        assert exc.value.status_code == 401


class TestRoleName:
    async def test_returns_role_name(self, db, org, admin_user):
        assert await current_org_role_name(admin_user, org.id, db) == "Admin"

    async def test_none_when_not_a_member(self, db, org, other_org, admin_user):
        assert await current_org_role_name(admin_user, other_org.id, db) is None


def _mounted_paths(router) -> set[str]:
    """收集 router（含 include_router 产生的嵌套结构）里所有路由路径。

    新版 FastAPI 的 `include_router` 会往 `routes` 里塞 `_IncludedRouter`
    包装对象（真正的 APIRouter 在它的 `original_router` 上）而不是直接展开成
    APIRoute，所以要递归下去。
    """
    paths: set[str] = set()
    for route in getattr(router, "routes", []):
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        nested = getattr(route, "original_router", None)
        if nested is not None:
            paths |= _mounted_paths(nested)
    return paths


class TestExtRouterMounting:
    def test_health_is_mounted(self):
        assert "/health" in _mounted_paths(include_all())

    def test_include_all_is_idempotent(self):
        first = len(include_all().routes)
        second = len(include_all().routes)
        assert first == second

    def test_enabled_tools_matches_submodules(self):
        assert enabled_tools() == [
            m if isinstance(m, str) else m[0] for m in SUBMODULES
        ]
        assert "health" in enabled_tools()


class TestExtHealthEndpoint:
    async def test_returns_identity_and_tools(self, db, org, admin_user):
        from src.routers.ext.health import api_ext_health

        result = await api_ext_health(
            org_id=org.id, db_session=db, current_user=admin_user
        )
        assert result.status == "ok"
        assert result.org_id == org.id
        assert result.user_id == admin_user.id
        assert result.username == admin_user.username
        assert result.role == "Admin"
        assert "health" in result.tools
        assert result.ext_version
