"""学期复用：克隆课程 + 复制作业记录与题目 + 截止日期顺延；以及单独的批量顺延。

上游的 `POST /courses/{uuid}/clone` 只复制章节、活动、blocks 和文件，
**不复制 assignment / assignmenttask 两张表**（见 services/courses/courses.py
的 clone_course，全函数没有一次 Assignment 写入）。所以克隆出来的课里只有一个
空的作业壳活动，点进去没有题 —— 这里把作业记录补上。

移植自 skill/learnhouse/assignments.py 的 `copy_assignments` / `shift_due`。
原实现按活动名匹配源课程与目标课程的作业活动；这里是紧接着克隆做的，克隆保序
且一一对应，所以改成**按章节顺序与活动顺序配对**，比按名字匹配更准（同名活动
不会歧义）。

两个危险接口都遵循同一个约定：`confirm=false` 只返回将要发生什么的摘要，
一个字都不写；`confirm=true` 才真的执行。前端向导的「确认摘要」那一步用的就是
前者。
"""

import datetime as dt
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.assignments import Assignment, AssignmentTask
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.course_chapters import CourseChapter
from src.db.courses.courses import Course
from src.db.users import PublicUser
from src.security.rbac import AccessAction, check_resource_access
from src.services.courses.courses import clone_course

from .spec import SpecError

_COPY_FIELDS = (
    "description", "grading_type", "published", "auto_grading", "anti_copy_paste",
    "show_correct_answers", "allow_retries", "max_retries",
    "pass_threshold_percentage", "ungraded", "solution", "solution_reveal",
)


def shift_date(s: str | None, days: int) -> str | None:
    """把 'YYYY-MM-DD'（或带时间的 ISO）顺延 days 天，保持原格式。解析失败返回 None。"""
    if not s or not isinstance(s, str):
        return None
    head = s.strip()[:10]
    try:
        d = dt.datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return None
    return (d + dt.timedelta(days=int(days))).strftime("%Y-%m-%d") + s.strip()[10:]


async def _ordered_activities(course_id: int, db_session: AsyncSession) -> list[Activity]:
    """课程里所有活动，按（章节顺序，活动顺序）排好。"""
    rows = (await db_session.execute(
        select(Activity, CourseChapter.order, ChapterActivity.order)
        .join(ChapterActivity, ChapterActivity.activity_id == Activity.id)
        .join(CourseChapter, CourseChapter.chapter_id == ChapterActivity.chapter_id)
        .where(CourseChapter.course_id == course_id)
    )).all()
    rows.sort(key=lambda r: (r[1] or 0, r[2] or 0, r[0].id))
    return [r[0] for r in rows]


async def _course_or_404(course_uuid: str, db_session: AsyncSession) -> Course:
    course = (await db_session.execute(
        select(Course).where(Course.course_uuid == course_uuid)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


async def _assignments_of(course_id: int, db_session: AsyncSession) -> list[Assignment]:
    return list((await db_session.execute(
        select(Assignment).where(Assignment.course_id == course_id).order_by(Assignment.id)
    )).scalars().all())


# ---------------------------------------------------------------- 学期复用


async def clone_term(
    request: Request,
    course_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
    name: str | None = None,
    shift_days: int | None = None,
    due_date: str | None = None,
    unpublish: bool = True,
    confirm: bool = False,
) -> dict:
    """把一门课整体复制成新学期的课。

    `shift_days` 与 `due_date` 二选一（都不给就保留原截止日期）。
    `unpublish=True` 时新课程与其中的作业都置为未发布，避免学生提前看到。
    """
    if shift_days is not None and due_date is not None:
        raise SpecError("顺延天数和统一截止日期只能给一个")
    if due_date is not None and not _is_date(due_date):
        raise SpecError("截止日期「%s」格式不对，要 YYYY-MM-DD" % due_date)

    source = await _course_or_404(course_uuid, db_session)
    await check_resource_access(
        request, db_session, current_user, source.course_uuid, AccessAction.READ
    )

    src_assignments = await _assignments_of(source.id, db_session)

    def _new_due(old: str | None) -> str | None:
        if not old:
            return None
        if due_date is not None:
            return due_date
        if shift_days is not None:
            return shift_date(old, shift_days) or old
        return old

    plan = [
        {
            "title": a.title,
            "old_due_date": a.due_date,
            "new_due_date": _new_due(a.due_date),
            "task_count": len((await _tasks_of(a.id, db_session))),
        }
        for a in src_assignments
    ]

    summary = {
        "confirmed": False,
        "source_course_uuid": source.course_uuid,
        "source_course_name": source.name,
        "new_course_name": name or f"{source.name} (Copy)",
        "assignment_count": len(src_assignments),
        "assignments": plan,
        "shift_days": shift_days,
        "due_date": due_date,
        "unpublish": bool(unpublish),
        "note": "克隆会复制章节、内容页、文件与作业题目，但**不会**复制学生的提交与成绩。",
    }
    if not confirm:
        return summary

    # 真干活：先克隆课程本体（上游 service，自带 RBAC、用量与文件复制）
    new_course_read = await clone_course(request, source.course_uuid, current_user, db_session)
    new_course = await _course_or_404(new_course_read.course_uuid, db_session)

    if name:
        new_course.name = name
    if unpublish:
        new_course.published = False
        new_course.public = False
    new_course.update_date = str(dt.datetime.now())
    db_session.add(new_course)
    await db_session.commit()
    await db_session.refresh(new_course)

    # 按（章节顺序，活动顺序）把源课程的活动和新课程的活动一一配对
    src_acts = await _ordered_activities(source.id, db_session)
    new_acts = await _ordered_activities(new_course.id, db_session)
    copied, skipped = [], []
    if len(src_acts) != len(new_acts):
        skipped.append({
            "assignment": None,
            "reason": "克隆前后活动数量不一致（%d → %d），不敢配对，作业没有复制"
                      % (len(src_acts), len(new_acts)),
        })
        act_map: dict[int, Activity] = {}
    else:
        act_map = {s.id: n for s, n in zip(src_acts, new_acts)}

    chapter_of_activity = {
        ca.activity_id: ca.chapter_id
        for ca in (await db_session.execute(
            select(ChapterActivity).where(ChapterActivity.course_id == new_course.id)
        )).scalars().all()
    }

    for a in src_assignments:
        target_activity = act_map.get(a.activity_id)
        if target_activity is None:
            skipped.append({"assignment": a.title, "reason": "在新课程里找不到对应的作业活动"})
            continue
        chapter_id = chapter_of_activity.get(target_activity.id)
        if chapter_id is None:
            skipped.append({"assignment": a.title, "reason": "新课程里的活动没有挂在任何章节下"})
            continue

        new_due = _new_due(a.due_date)
        new_assignment = Assignment(
            title=a.title,
            due_date=new_due,
            org_id=new_course.org_id,
            course_id=new_course.id,
            chapter_id=chapter_id,
            activity_id=target_activity.id,
            assignment_uuid=str(f"assignment_{uuid4()}"),
            creation_date=str(dt.datetime.now()),
            update_date=str(dt.datetime.now()),
            **{f: getattr(a, f) for f in _COPY_FIELDS},
        )
        if unpublish:
            new_assignment.published = False
            target_activity.published = False
            db_session.add(target_activity)
        db_session.add(new_assignment)
        await db_session.flush()
        await db_session.refresh(new_assignment)

        made = 0
        for t in await _tasks_of(a.id, db_session):
            db_session.add(AssignmentTask(
                title=t.title,
                description=t.description,
                hint=t.hint,
                assignment_type=t.assignment_type,
                contents=t.contents,
                max_grade_value=t.max_grade_value,
                assignment_task_uuid=str(f"assignmenttask_{uuid4()}"),
                creation_date=str(dt.datetime.now()),
                update_date=str(dt.datetime.now()),
                assignment_id=new_assignment.id,
                org_id=new_course.org_id,
                course_id=new_course.id,
                chapter_id=chapter_id,
                activity_id=target_activity.id,
            ))
            made += 1

        copied.append({
            "title": a.title,
            "source_assignment_uuid": a.assignment_uuid,
            "assignment_uuid": new_assignment.assignment_uuid,
            "task_count": made,
            "old_due_date": a.due_date,
            "new_due_date": new_due,
        })

    await db_session.commit()

    summary.update({
        "confirmed": True,
        "new_course_uuid": new_course.course_uuid,
        "new_course_name": new_course.name,
        "copied_count": len(copied),
        "copied": copied,
        "skipped_count": len(skipped),
        "skipped": skipped,
    })
    return summary


async def _tasks_of(assignment_id: int, db_session: AsyncSession) -> list[AssignmentTask]:
    return list((await db_session.execute(
        select(AssignmentTask)
        .where(AssignmentTask.assignment_id == assignment_id)
        .order_by(AssignmentTask.id)
    )).scalars().all())


def _is_date(s) -> bool:
    try:
        dt.datetime.strptime(str(s).strip()[:10], "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- 批量顺延


async def shift_due(
    request: Request,
    course_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
    days: int | None = None,
    due_date: str | None = None,
    only_future: bool = False,
    confirm: bool = False,
) -> dict:
    """把课程里所有作业的截止日期整体顺延 days 天，或统一设成 due_date。

    没有设过截止日期的作业一律跳过 —— 不给它凭空补一个。
    `only_future=True` 时只动还没到期的作业。
    """
    if (days is None) == (due_date is None):
        raise SpecError("顺延天数和统一截止日期必须给且只能给一个")
    if due_date is not None and not _is_date(due_date):
        raise SpecError("截止日期「%s」格式不对，要 YYYY-MM-DD" % due_date)

    course = await _course_or_404(course_uuid, db_session)
    await check_resource_access(
        request, db_session, current_user, course.course_uuid, AccessAction.UPDATE
    )

    today = dt.date.today()
    changed, skipped = [], []
    for a in await _assignments_of(course.id, db_session):
        old = a.due_date
        if not old:
            skipped.append({"title": a.title, "reason": "没有设过截止日期"})
            continue
        if shift_date(old, 0) is None:
            skipped.append({"title": a.title, "reason": "截止日期格式看不懂：%s" % old})
            continue
        if only_future:
            try:
                if dt.datetime.strptime(old.strip()[:10], "%Y-%m-%d").date() < today:
                    skipped.append({
                        "title": a.title,
                        "reason": "已过期（%s），只顺延未到期的作业时跳过" % old,
                    })
                    continue
            except ValueError:
                pass
        new = shift_date(old, days) if days is not None else due_date
        row = {
            "assignment_uuid": a.assignment_uuid, "title": a.title,
            "old_due_date": old, "new_due_date": new,
        }
        if confirm:
            a.due_date = new
            a.update_date = str(dt.datetime.now())
            db_session.add(a)
        changed.append(row)

    if confirm:
        await db_session.commit()

    return {
        "confirmed": bool(confirm),
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "days": days,
        "due_date": due_date,
        "only_future": bool(only_future),
        "changed_count": len(changed), "changed": changed,
        "skipped_count": len(skipped), "skipped": skipped,
    }
