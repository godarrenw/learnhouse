"""内容页版本：列表、按版本取 Markdown、两版之间的 unified diff、回滚。

移植自 skill/learnhouse/versions.py。版本表和读写逻辑上游已经有了
（db/courses/activity_versions.py、services/courses/activities/versioning.py），
这里只补三件上游没有的事：把版本内容渲染成 Markdown、按行做 unified diff、
以及给回滚加一道 confirm 闸门。

**回滚前会先把当前内容存成新版本** —— 这是上游 `restore_activity_version`
自带的行为，不是这里另加的，所以回滚不会丢掉当前稿。
"""

import difflib

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.courses import Course
from src.db.users import PublicUser
from src.security.rbac import AccessAction, check_resource_access
from src.services.courses.activities.versioning import (
    get_activity_version,
    get_activity_versions,
    restore_activity_version,
)

from .tiptap import tiptap_to_markdown

DIFF_CONTEXT_LINES = 3


async def _activity_or_404(activity_uuid: str, db_session: AsyncSession) -> tuple[Activity, Course]:
    activity = (await db_session.execute(
        select(Activity).where(Activity.activity_uuid == activity_uuid)
    )).scalars().first()
    if not activity:
        raise HTTPException(status_code=404, detail="内容页不存在")
    course = (await db_session.execute(
        select(Course).where(Course.id == activity.course_id)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return activity, course


async def _require_course_editor(
    request: Request,
    course: Course,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> None:
    """版本相关的接口一律按「能改这门课的人」判，而不是「能看这门课的人」。

    这几个接口都是只读的，但它们返回的是内容页的历史稿与逐行 diff —— 包括还没
    发布的草稿。公开课程的 READ 对任何登录用户都成立，用 READ 判就等于把本组织
    每一门课的编辑历史开放给了每一个教师账号，Instructor 尤其不该看到别人课的
    草稿。所以这里显式再要一次 UPDATE。

    上游 `get_activity_versions` / `get_activity_version` 内部还有一道 READ，
    留着无妨：更严的这道先过。
    """
    await check_resource_access(
        request, db_session, current_user, course.course_uuid, AccessAction.UPDATE
    )


async def list_versions(
    request: Request,
    activity_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
    limit: int = 20,
) -> dict:
    """版本列表，外加当前版本号 —— 前端要靠它把「当前」标出来。"""
    activity, course = await _activity_or_404(activity_uuid, db_session)
    await _require_course_editor(request, course, current_user, db_session)
    versions = await get_activity_versions(
        request, activity_uuid, current_user, db_session, limit=limit, offset=0
    )
    return {
        "activity_uuid": activity.activity_uuid,
        "activity_name": activity.name,
        "course_uuid": course.course_uuid,
        "current_version": activity.current_version,
        "versions": [
            {
                "version_number": v.version_number,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "created_by_username": v.created_by_username,
                "created_by_avatar": v.created_by_avatar,
                "chars": len(tiptap_to_markdown(v.content or {})),
            }
            for v in versions
        ],
    }


async def _markdown_of(
    request: Request,
    activity: Activity,
    version_number: int | None,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> tuple[str, str]:
    """取某个版本的 Markdown；version_number 为 None 表示当前内容。返回 (文本, 标签)。"""
    if version_number is None:
        return (
            tiptap_to_markdown(activity.content or {}),
            "当前（v%d）" % activity.current_version,
        )
    version = await get_activity_version(
        request, activity.activity_uuid, version_number, current_user, db_session
    )
    return tiptap_to_markdown(version.content or {}), "v%d" % version_number


async def version_markdown(
    request: Request,
    activity_uuid: str,
    version_number: int,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> dict:
    """把某个版本的内容渲染成 Markdown 给前端预览。"""
    activity, course = await _activity_or_404(activity_uuid, db_session)
    await _require_course_editor(request, course, current_user, db_session)
    markdown, label = await _markdown_of(
        request, activity, version_number, current_user, db_session
    )
    return {
        "activity_uuid": activity.activity_uuid,
        "course_uuid": course.course_uuid,
        "version_number": version_number,
        "label": label,
        "markdown": markdown,
    }


async def diff_versions(
    request: Request,
    activity_uuid: str,
    a: int | None,
    b: int | None,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> dict:
    """两个版本之间的 unified diff。任一侧传 None 表示「当前内容」。

    diff 做在 Markdown 文本行上，不是 tiptap JSON 上 —— JSON 的 diff 全是
    结构噪音，老师看不出改了哪句话。
    """
    activity, course = await _activity_or_404(activity_uuid, db_session)
    await _require_course_editor(request, course, current_user, db_session)
    text_a, label_a = await _markdown_of(request, activity, a, current_user, db_session)
    text_b, label_b = await _markdown_of(request, activity, b, current_user, db_session)

    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    diff_lines = list(difflib.unified_diff(
        lines_a, lines_b, fromfile=label_a, tofile=label_b,
        lineterm="", n=DIFF_CONTEXT_LINES,
    ))
    added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

    return {
        "activity_uuid": activity.activity_uuid,
        "course_uuid": course.course_uuid,
        "a": a, "b": b,
        "label_a": label_a, "label_b": label_b,
        "markdown_a": text_a, "markdown_b": text_b,
        "diff": "\n".join(diff_lines),
        "added_lines": added,
        "removed_lines": removed,
        "identical": not diff_lines,
    }


async def restore(
    request: Request,
    activity_uuid: str,
    version_number: int,
    current_user: PublicUser,
    db_session: AsyncSession,
    confirm: bool = False,
) -> dict:
    """回滚到某个版本。confirm=false 只返回摘要，一个字都不写。"""
    activity, course = await _activity_or_404(activity_uuid, db_session)

    if not confirm:
        # 预览返回的是完整 diff，和上面那三个只读接口是同一类东西，
        # 所以门槛也一样按 update 判，不能因为「只是预览」就放低。
        await _require_course_editor(request, course, current_user, db_session)
        preview = await diff_versions(
            request, activity_uuid, None, version_number, current_user, db_session
        )
        return {
            "confirmed": False,
            "activity_uuid": activity.activity_uuid,
            "activity_name": activity.name,
            "current_version": activity.current_version,
            "restore_to": version_number,
            "added_lines": preview["added_lines"],
            "removed_lines": preview["removed_lines"],
            "diff": preview["diff"],
            "note": "回滚前会先把当前内容存成一个新版本，所以现在这一稿不会丢。",
        }

    restored = await restore_activity_version(
        request, activity_uuid, version_number, current_user, db_session
    )
    return {
        "confirmed": True,
        "activity_uuid": restored.activity_uuid,
        "activity_name": restored.name,
        "restored_from_version": version_number,
        "current_version": restored.current_version,
        "note": "回滚前的内容已经存成上一个版本，可以再回滚回去。",
    }
