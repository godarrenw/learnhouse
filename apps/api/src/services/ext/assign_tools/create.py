"""按 spec 建作业：作业壳活动 + assignment 记录 + 每道题。

移植自 skill/learnhouse/assignments.py 的 `create_assignment_from_spec`，
但改成复用上游的 service 函数（create_activity / create_assignment /
create_assignment_task），这样 RBAC、用量统计、webhook 的行为和从网页上手工
建作业完全一致。
"""

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import (
    ActivityCreate,
    ActivityLockType,
    ActivitySubTypeEnum,
    ActivityTypeEnum,
)
from src.db.courses.assignments import (
    AssignmentCreate,
    AssignmentTaskCreate,
    AssignmentTaskTypeEnum,
    GradingTypeEnum,
    SolutionRevealEnum,
)
from src.db.courses.chapters import Chapter
from src.db.courses.courses import Course
from src.db.users import PublicUser
from src.services.courses.activities.activities import create_activity
from src.services.courses.activities.assignments import (
    create_assignment,
    create_assignment_task,
)

from .spec import validate_spec


async def _resolve_chapter(
    course_uuid: str, chapter_id: int, db_session: AsyncSession
) -> tuple[Course, Chapter]:
    course = (await db_session.execute(
        select(Course).where(Course.course_uuid == course_uuid)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    chapter = (await db_session.execute(
        select(Chapter).where(Chapter.id == chapter_id)
    )).scalars().first()
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    if chapter.course_id != course.id:
        raise HTTPException(status_code=400, detail="这个章节不属于该课程")
    return course, chapter


async def create_from_spec(
    request: Request,
    course_uuid: str,
    chapter_id: int,
    raw_spec: dict,
    current_user: PublicUser,
    db_session: AsyncSession,
    publish_override: bool | None = None,
) -> dict:
    """一份 spec 建出完整作业。

    校验在建任何东西之前完成，避免留下半截作业。`publish_override` 让前端的
    「一键布置」按钮直接决定发布与否，不用改 spec 本身。
    """
    course, chapter = await _resolve_chapter(course_uuid, chapter_id, db_session)

    checked = validate_spec(raw_spec)
    publish = checked["publish"] if publish_override is None else bool(publish_override)

    clean = {k: v for k, v in raw_spec.items() if not str(k).startswith("_")}

    activity = await create_activity(
        request,
        ActivityCreate(
            name=checked["name"],
            chapter_id=chapter.id,
            activity_type=ActivityTypeEnum.TYPE_ASSIGNMENT,
            activity_sub_type=ActivitySubTypeEnum.SUBTYPE_ASSIGNMENT_ANY,
            content={},
            details={},
            published=publish,
            lock_type=ActivityLockType.PUBLIC,
        ),
        current_user,
        db_session,
    )

    assignment = await create_assignment(
        request,
        AssignmentCreate(
            title=checked["name"],
            description=clean.get("description", "") or "",
            due_date=checked["due_date"],
            published=publish,
            grading_type=GradingTypeEnum(checked["grading_type"]),
            auto_grading=bool(clean.get("auto_grading", True)),
            anti_copy_paste=bool(clean.get("anti_copy_paste", False)),
            show_correct_answers=bool(clean.get("show_correct_answers", False)),
            allow_retries=bool(clean.get("allow_retries", False)),
            max_retries=int(clean.get("max_retries", 0) or 0),
            pass_threshold_percentage=clean.get("pass_threshold"),
            # spec 里叫 formative（形成性、不计分），对应后端字段 ungraded
            ungraded=bool(clean.get("formative", clean.get("ungraded", False))),
            solution=clean.get("solution"),
            solution_reveal=SolutionRevealEnum(checked["solution_reveal"]),
            org_id=course.org_id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=activity.id,
        ),
        current_user,
        db_session,
    )

    made = []
    for t in checked["tasks"]:
        task = await create_assignment_task(
            request,
            assignment.assignment_uuid,
            AssignmentTaskCreate(
                title=t["title"],
                description=t["description"],
                hint=t["hint"],
                assignment_type=AssignmentTaskTypeEnum(t["type"]),
                contents=t["contents"],
                max_grade_value=t["max_grade_value"],
            ),
            current_user,
            db_session,
        )
        made.append({
            "assignment_task_uuid": task.assignment_task_uuid,
            "title": task.title,
            "kind": t["kind"],
        })

    return {
        "course_uuid": course.course_uuid,
        "chapter_id": chapter.id,
        "activity_uuid": activity.activity_uuid,
        "assignment_uuid": assignment.assignment_uuid,
        "title": checked["name"],
        "published": publish,
        "task_count": len(made),
        "tasks": made,
        "warnings": checked["warnings"],
    }
