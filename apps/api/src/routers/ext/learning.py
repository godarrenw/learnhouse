# -*- coding: utf-8 -*-
"""学情工具接口：成绩册、缺交名单、学习进度、课程体检。

路由层很薄：只做 HTTP 签名、权限入口和 CSV 包装，业务逻辑全在
`src/services/ext/learning/` 里。

三层权限，缺一不可：
1. `router.py` 挂载时的 `require_authenticated_user`（拒匿名、拒 API token）
2. `deps.require_teacher`：调用者在 `?org_id=` 那个组织里是 Admin / Maintainer / Instructor
3. `rbac_check_course`：调用者必须**能改这门具体课程**（作者 / 课程管理员 / Admin
   / Maintainer）。四个只读接口也判 update 而不是 read —— 它们吐的是学生姓名、
   成绩和学习记录，而 read 权限对公开课程的任何登录用户都成立，按 read 判等于
   把全班数据开放给选课的人。

另外每个带 course_uuid 的接口都会核对课程确实属于 `org_id` 那个组织，
防止拿 A 组织的教师身份去读 B 组织的课。
"""

from typing import Optional

from fastapi import APIRouter, Body, Depends, Query, Request
from fastapi.responses import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import PublicUser
from src.routers.ext.deps import require_teacher
from src.services.ext.learning.common import rbac_check_course, resolve_course
from src.services.ext.learning.gradebook import (
    build_gradebook,
    build_missing,
    gradebook_csv,
    missing_csv,
)
from src.services.ext.learning.lint import fix_publish, lint_course
from src.services.ext.learning.progress import (
    build_progress,
    build_recent,
    build_student_progress,
    progress_csv,
)

router = APIRouter()


def _csv_response(payload: bytes, filename: str) -> Response:
    """CSV 一律带 UTF-8 BOM，Excel 双击打开中文不乱码。"""
    return Response(
        content=payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="%s"' % filename},
    )


@router.get(
    "/courses/{course_uuid}/gradebook",
    tags=["ext"],
    summary="成绩册（学生 × 作业矩阵）",
    description=(
        "返回这门课的成绩册：学生集合 = 绑定课程的用户组成员 ∪ 有提交记录的人。"
        "单元格给原始分与百分比，行尾给总分与平均百分比。"
        "`format=csv` 时返回 UTF-8 BOM 的 CSV 文件。"
    ),
    responses={
        200: {"description": "成绩册数据，或 CSV 文件"},
        401: {"description": "未登录"},
        403: {"description": "不是教师，或对这门课没有修改权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_gradebook(
    *,
    request: Request,
    course_uuid: str,
    org_id: int = Query(..., description="组织 id"),
    format: Optional[str] = Query(None, pattern="^(json|csv)$"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    course = await resolve_course(db_session, course_uuid, org_id)
    await rbac_check_course(request, course_uuid, current_user, "update", db_session)
    data = await build_gradebook(db_session, course)
    if format == "csv":
        return _csv_response(gradebook_csv(data), "gradebook-%s.csv" % course_uuid[:8])
    return data


@router.get(
    "/courses/{course_uuid}/missing",
    tags=["ext"],
    summary="缺交名单",
    description=(
        "按班级名单（绑定这门课的用户组成员）对比提交记录，列出谁没交。"
        "给了 assignment_uuid 就只看那一份作业。`format=csv` 返回 CSV。"
    ),
    responses={
        200: {"description": "缺交名单，或 CSV 文件"},
        400: {"description": "作业不属于这门课"},
        401: {"description": "未登录"},
        403: {"description": "不是教师，或对这门课没有修改权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_missing(
    *,
    request: Request,
    course_uuid: str,
    org_id: int = Query(..., description="组织 id"),
    assignment_uuid: Optional[str] = None,
    format: Optional[str] = Query(None, pattern="^(json|csv)$"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    course = await resolve_course(db_session, course_uuid, org_id)
    await rbac_check_course(request, course_uuid, current_user, "update", db_session)
    data = await build_missing(db_session, course, assignment_uuid)
    if format == "csv":
        return _csv_response(missing_csv(data), "missing-%s.csv" % course_uuid[:8])
    return data


@router.get(
    "/courses/{course_uuid}/progress",
    tags=["ext"],
    summary="学习进度",
    description=(
        "每个学生完成的活动数 / 活动总数 / 完成度 / 最近学习时间。"
        "分母沿用后端 trail 服务的算法（课程下挂在章节里的活动总数，含未发布活动），"
        "所以和学生自己看到的百分比一致。给了 student（user_uuid 或 user_id）"
        "就返回这个人的明细：完成了哪些活动、什么时候完成的。"
    ),
    responses={
        200: {"description": "进度数据，或 CSV 文件"},
        401: {"description": "未登录"},
        403: {"description": "不是教师，或对这门课没有修改权限"},
        404: {"description": "课程或学生不存在"},
    },
)
async def api_progress(
    *,
    request: Request,
    course_uuid: str,
    org_id: int = Query(..., description="组织 id"),
    student: Optional[str] = None,
    format: Optional[str] = Query(None, pattern="^(json|csv)$"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    course = await resolve_course(db_session, course_uuid, org_id)
    await rbac_check_course(request, course_uuid, current_user, "update", db_session)
    if student:
        return await build_student_progress(db_session, course, student)
    data = await build_progress(db_session, course)
    if format == "csv":
        return _csv_response(progress_csv(data), "progress-%s.csv" % course_uuid[:8])
    return data


@router.get(
    "/recent",
    tags=["ext"],
    summary="最近学习事件",
    description=(
        "组织范围内最近 N 天的学习事件：完成 / 打开活动、开始学习课程。"
        "按时间倒序，最多返回 limit 条。"
    ),
    responses={
        200: {"description": "事件列表"},
        401: {"description": "未登录"},
        403: {"description": "不是教师，或不是这个组织的成员"},
    },
)
async def api_recent(
    *,
    org_id: int = Query(..., description="组织 id"),
    days: int = Query(7, ge=1, le=365),
    limit: int = Query(200, ge=1, le=1000),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    # 组织级鉴权已经由 require_teacher 做掉，这里直接查
    return await build_recent(db_session, org_id, days=days, limit=limit)


@router.get(
    "/courses/{course_uuid}/lint",
    tags=["ext"],
    summary="课程体检",
    description=(
        "开课前跑一遍，把「学生打不开 / 看到半成品」的问题一次列全，"
        "分 error / warn / info 三级，每条带 target_uuid 与修复建议。"
    ),
    responses={
        200: {"description": "体检结果"},
        401: {"description": "未登录"},
        403: {"description": "不是教师，或对这门课没有修改权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_lint(
    *,
    request: Request,
    course_uuid: str,
    org_id: int = Query(..., description="组织 id"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    course = await resolve_course(db_session, course_uuid, org_id)
    await rbac_check_course(request, course_uuid, current_user, "update", db_session)
    return await lint_course(db_session, course)


@router.post(
    "/courses/{course_uuid}/lint/fix-publish",
    tags=["ext"],
    summary="一键发布未发布的活动",
    description=(
        "把体检里「还没发布」的活动发布出去。只发没有 error 级问题的活动，"
        "作业壳一律跳过（只发活动学生仍然做不了）。请求体必须带 confirm: true。"
        "需要对这门课有 update 权限。"
    ),
    responses={
        200: {"description": "发布结果（已发布 / 已跳过及原因）"},
        400: {"description": "没有带 confirm: true"},
        401: {"description": "未登录"},
        403: {"description": "不是教师，或对这门课没有修改权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_lint_fix_publish(
    *,
    request: Request,
    course_uuid: str,
    org_id: int = Query(..., description="组织 id"),
    body: dict = Body(default_factory=dict),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(require_teacher),
):
    course = await resolve_course(db_session, course_uuid, org_id)
    await rbac_check_course(request, course_uuid, current_user, "update", db_session)
    return await fix_publish(db_session, course, body.get("confirm") is True)
