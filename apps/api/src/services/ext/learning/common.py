# -*- coding: utf-8 -*-
"""学情工具的公共零件：课程解析、课程级权限、名单、时间与 CSV。

业务逻辑移植自 learnhouse-agent/skill/learnhouse/{progress,trail,tools}.py，
区别是后端能直接查库，不再走 HTTP API，也不再 SSH 到 NAS。
"""

import csv
import io
import os
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import HTTPException, Request, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.courses import Course
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.users import AnonymousUser, APITokenUser, InternalUser, PublicUser, User
from src.security.rbac.rbac import (
    authorization_verify_based_on_roles_and_authorship,
    authorization_verify_if_user_is_anon,
)

# 显示时区。库里所有 creation_date / update_date 都是 `str(datetime.now())` 写下的
# **无时区**字符串，生产容器的 TZ 是 UTC，所以按 UTC 解析再转成这里的时区输出。
# 想换成别的时区，改 apps/api/.env 的 LEARNHOUSE_EXT_TIMEZONE_OFFSET（单位：小时）。
DISPLAY_TZ_OFFSET_HOURS = float(os.environ.get("LEARNHOUSE_EXT_TIMEZONE_OFFSET", "8"))
DISPLAY_TZ = timezone(timedelta(hours=DISPLAY_TZ_OFFSET_HOURS))

# 单次查询的行上限，防止一门大课把整库拖下来
ROW_LIMIT = 5000

# 「没交」的状态集合，和 skill 里 progress.py 的判断保持一致
NOT_SUBMITTED_STATUSES = {None, "", "NOT_SUBMITTED", "PENDING"}


class LearningError(HTTPException):
    """参数或数据本身的问题，消息是中文，直接给用户看。"""

    def __init__(self, detail: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(status_code=status_code, detail=detail)


# ---------------------------------------------------------------- 时间


def to_iso(raw: str | None) -> str | None:
    """把库里的 naive 时间字符串（UTC）转成带时区的 ISO 8601 字符串。

    '2026-09-08 11:30:31.402905' → '2026-09-08T19:30:31.402905+08:00'
    解析不了就返回 None，不抛异常（历史数据里空串很常见）。
    """
    if not raw:
        return None
    text = str(raw).strip().replace("T", " ")
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc).astimezone(DISPLAY_TZ).isoformat()
    return None


def parse_naive(raw: str | None) -> datetime | None:
    """把 ISO datetime 或 'YYYY-MM-DD' 解析成 naive datetime，解析不了返回 None。"""
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def due_cutoff(raw: str | None) -> datetime | None:
    """把作业 due_date 折成「过了这个时刻才算迟交」的截止时刻。

    与服务端 `_is_assignment_past_due()` 同一套规则：只有日期没有时间的 due_date
    （前端 <input type="date"> 就是这种）**整个当天都算按时**，所以顺延到次日零点。
    """
    parsed = parse_naive(raw)
    if parsed is None:
        return None
    text = (raw or "").strip()
    if "T" not in text and ":" not in text:
        parsed = parsed + timedelta(days=1)
    return parsed


# ---------------------------------------------------------------- 课程与权限


async def resolve_course(db_session: AsyncSession, course_uuid: str) -> Course:
    """按 course_uuid 取课程，取不到就 404。"""
    result = await db_session.execute(
        select(Course).where(Course.course_uuid == course_uuid)
    )
    course = result.scalars().first()
    if not course:
        raise LearningError("找不到这门课程", status.HTTP_404_NOT_FOUND)
    return course


async def rbac_check_course(
    request: Request,
    course_uuid: str,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    action: Literal["read", "update"],
    db_session: AsyncSession,
):
    """课程级权限：调用者对这门课要有对应权限，否则 403。

    与上游 service 的写法一致（每个 service 自己定义 rbac_check，路由不判权限）。
    """
    if isinstance(current_user, InternalUser):
        return True
    await authorization_verify_if_user_is_anon(current_user.id)
    await authorization_verify_based_on_roles_and_authorship(
        request, current_user.id, action, course_uuid, db_session
    )
    return True


# ---------------------------------------------------------------- 名单


def display_name(user: User) -> str:
    """姓名优先，没有就退回用户名。"""
    full = " ".join(x for x in [user.first_name or "", user.last_name or ""] if x).strip()
    return full or user.username


async def linked_usergroups(
    db_session: AsyncSession, course_uuid: str, org_id: int
) -> list[UserGroup]:
    """找出绑定了这门课的所有用户组。"""
    result = await db_session.execute(
        select(UserGroup)
        .join(UserGroupResource, UserGroupResource.usergroup_id == UserGroup.id)  # type: ignore[arg-type]
        .where(UserGroupResource.resource_uuid == course_uuid)
        .where(UserGroup.org_id == org_id)
    )
    return list(result.scalars().unique().all())


async def roster(
    db_session: AsyncSession, course_uuid: str, org_id: int
) -> tuple[dict[int, dict], list[dict]]:
    """班级名单 = 绑定这门课的用户组成员。

    返回 (user_id → {user_id, name, email, usergroup}, 用户组简表)。
    一个人在多个组里时，usergroup 字段列出全部组名（顿号分隔）。
    """
    groups = await linked_usergroups(db_session, course_uuid, org_id)
    if not groups:
        return {}, []

    group_ids = [g.id for g in groups if g.id is not None]
    result = await db_session.execute(
        select(User, UserGroupUser.usergroup_id)
        .join(UserGroupUser, UserGroupUser.user_id == User.id)  # type: ignore[arg-type]
        .where(UserGroupUser.usergroup_id.in_(group_ids))  # type: ignore[union-attr]
        .limit(ROW_LIMIT)
    )
    group_names = {g.id: g.name for g in groups}
    people: dict[int, dict] = {}
    for user, usergroup_id in result.all():
        entry = people.setdefault(
            user.id,
            {
                "user_id": user.id,
                "user_uuid": user.user_uuid,
                "name": display_name(user),
                "email": user.email,
                "usergroups": [],
            },
        )
        name = group_names.get(usergroup_id)
        if name and name not in entry["usergroups"]:
            entry["usergroups"].append(name)
    for entry in people.values():
        entry["usergroup"] = "、".join(entry["usergroups"])
        entry.pop("usergroups")
    return people, [{"id": g.id, "name": g.name} for g in groups]


async def users_by_id(db_session: AsyncSession, user_ids: list[int]) -> dict[int, User]:
    """按 id 批量取用户，用于补齐「组外但有提交/有学习记录」的人。"""
    if not user_ids:
        return {}
    result = await db_session.execute(select(User).where(User.id.in_(user_ids)))  # type: ignore[union-attr]
    return {u.id: u for u in result.scalars().all()}


# ---------------------------------------------------------------- CSV


def csv_bytes(fieldnames: list[str], rows: list[dict]) -> bytes:
    """写成 UTF-8 BOM 的 CSV 字节流，Excel 双击打开中文不乱码。"""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")
