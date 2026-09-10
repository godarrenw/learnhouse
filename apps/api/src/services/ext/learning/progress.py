# -*- coding: utf-8 -*-
"""学习进度与最近学习事件。

移植自 learnhouse-agent/skill/learnhouse/trail.py。skill 版本因为线上
`/analytics/dashboard/*` 全部 503、HTTP API 又没有「教师看某个学生进度」的接口，
只能 SSH 到 NAS 直连 Postgres；后端在容器内可以直接查 trail / trailrun / trailstep，
所以这里不再有任何 SSH 或密码。

**百分比的分母**沿用后端 trail 服务的算法：
`SELECT count(*) FROM chapteractivity WHERE course_id = ?`，
也就是课程下挂在章节里的活动总数，**含未发布的活动**。换别的算法会和
学生在网页上看到的百分比对不上，所以接口返回里带 `denominator_note` 说明。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.chapter_activities import ChapterActivity
from src.db.courses.chapters import Chapter
from src.db.courses.courses import Course
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.users import User
from src.services.ext.learning.common import (
    ROW_LIMIT,
    LearningError,
    csv_bytes,
    display_name,
    roster,
    to_iso,
    users_by_id,
)

DENOMINATOR_NOTE = (
    "完成度的分母 = 课程下挂在章节里的活动总数（含未发布的活动），"
    "与平台内部 trail 服务的算法一致。时间已从 UTC 转成展示时区。"
)


async def _total_activities(db_session: AsyncSession, course_id: int) -> int:
    result = await db_session.execute(
        select(func.count(ChapterActivity.id)).where(  # type: ignore[arg-type]
            ChapterActivity.course_id == course_id
        )
    )
    return int(result.scalar() or 0)


async def _activity_index(db_session: AsyncSession, course_id: int) -> dict[int, dict]:
    """activity_id → {name, chapter, activity_uuid, published, order}。"""
    result = await db_session.execute(
        select(Activity, Chapter.name, ChapterActivity.order)
        .join(ChapterActivity, ChapterActivity.activity_id == Activity.id)  # type: ignore[arg-type]
        .join(Chapter, Chapter.id == ChapterActivity.chapter_id)  # type: ignore[arg-type]
        .where(ChapterActivity.course_id == course_id)
        .limit(ROW_LIMIT)
    )
    index: dict[int, dict] = {}
    for activity, chapter_name, order in result.all():
        index[activity.id] = {
            "activity_uuid": activity.activity_uuid,
            "name": activity.name,
            "chapter": chapter_name,
            "published": bool(activity.published),
            "order": order,
        }
    return index


async def build_progress(db_session: AsyncSession, course) -> dict:
    """一门课里每个学生完成了多少活动、完成度、最近一次学习时间。"""
    total = await _total_activities(db_session, course.id)
    students, groups = await roster(db_session, course.course_uuid, course.org_id)

    # 每个学生完成的活动数。唯一约束在上游标了「需要迁移才生效」，线上可能有重复行，
    # 所以用 distinct(activity_id) 去重，避免完成数虚高。
    step_result = await db_session.execute(
        select(
            TrailStep.user_id,
            func.count(func.distinct(TrailStep.activity_id)),
            func.max(TrailStep.creation_date),
        )
        .where(TrailStep.course_id == course.id)
        .where(TrailStep.complete == True)  # noqa: E712 — SQLAlchemy 需要 ==
        .group_by(TrailStep.user_id)  # type: ignore[arg-type]
    )
    completed_by_user = {
        row[0]: {"completed": int(row[1] or 0), "last_step": row[2]}
        for row in step_result.all()
    }

    run_result = await db_session.execute(
        select(TrailRun).where(TrailRun.course_id == course.id).limit(ROW_LIMIT)
    )
    runs = {run.user_id: run for run in run_result.scalars().all()}

    # 名单外但有学习记录的人也列出来（比如公开课里自己进来的）
    extra_ids = sorted(
        {uid for uid in set(completed_by_user) | set(runs) if uid not in students}
    )
    for uid, user in (await users_by_id(db_session, extra_ids)).items():
        students[uid] = {
            "user_id": uid,
            "user_uuid": user.user_uuid,
            "name": display_name(user),
            "email": user.email,
            "usergroup": "（组外，有学习记录）",
        }

    rows = []
    for uid in sorted(students):
        row = dict(students[uid])
        stats = completed_by_user.get(uid, {})
        run = runs.get(uid)
        completed = stats.get("completed", 0)
        last_raw = stats.get("last_step")
        if run is not None and (run.update_date or "") > (last_raw or ""):
            last_raw = run.update_date
        row.update(
            {
                "completed": completed,
                "total_activities": total,
                "percentage": round(completed * 100.0 / total, 1) if total else None,
                "status": getattr(run.status, "value", run.status) if run else None,
                "started_at": to_iso(run.creation_date) if run else None,
                "last_active_at": to_iso(last_raw),
                "has_started": run is not None or completed > 0,
            }
        )
        rows.append(row)

    out = {
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "usergroups": groups,
        "total_activities": total,
        "student_count": len(rows),
        "students": rows,
        "denominator_note": DENOMINATOR_NOTE,
    }
    if not rows:
        out["note"] = (
            "这门课还没有任何学生的学习记录 —— 学生第一次打开课程才会生成 trailrun。"
        )
    return out


async def build_student_progress(
    db_session: AsyncSession, course, student: str
) -> dict:
    """单个学生在这门课里的明细：完成了哪些活动、什么时候完成的。

    student 接受 user_uuid，也接受纯数字的 user_id。
    """
    statement = select(User).where(User.user_uuid == student)
    if str(student).isdigit():
        statement = select(User).where(User.id == int(student))
    user = (await db_session.execute(statement)).scalars().first()
    if not user:
        raise LearningError("找不到这个学生", 404)

    total = await _total_activities(db_session, course.id)
    activities = await _activity_index(db_session, course.id)

    step_result = await db_session.execute(
        select(TrailStep)
        .where(TrailStep.course_id == course.id)
        .where(TrailStep.user_id == user.id)
        .limit(ROW_LIMIT)
    )
    # 同一个活动可能有重复行（唯一约束未必已迁移），保留最早那条
    earliest: dict[int, TrailStep] = {}
    for step in step_result.scalars().all():
        current = earliest.get(step.activity_id)
        if current is None or (step.creation_date or "") < (current.creation_date or ""):
            earliest[step.activity_id] = step

    run = (
        await db_session.execute(
            select(TrailRun)
            .where(TrailRun.course_id == course.id)
            .where(TrailRun.user_id == user.id)
        )
    ).scalars().first()

    steps, completed = [], 0
    for activity_id in sorted(
        earliest, key=lambda aid: (activities.get(aid, {}).get("order") or 0, aid)
    ):
        step = earliest[activity_id]
        meta = activities.get(activity_id, {})
        if step.complete:
            completed += 1
        steps.append(
            {
                "activity_id": activity_id,
                "activity_uuid": meta.get("activity_uuid"),
                "activity_name": meta.get("name")
                or "（活动 %s，已删除或不在本课结构里）" % activity_id,
                "chapter": meta.get("chapter"),
                "published": meta.get("published"),
                "complete": bool(step.complete),
                "teacher_verified": bool(step.teacher_verified),
                "grade": step.grade or "",
                "completed_at": to_iso(step.creation_date),
            }
        )

    return {
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "user_id": user.id,
        "user_uuid": user.user_uuid,
        "name": display_name(user),
        "email": user.email,
        "status": getattr(run.status, "value", run.status) if run else None,
        "started_at": to_iso(run.creation_date) if run else None,
        "last_active_at": to_iso(run.update_date) if run else None,
        "completed": completed,
        "total_activities": total,
        "percentage": round(completed * 100.0 / total, 1) if total else None,
        "steps": steps,
        "denominator_note": DENOMINATOR_NOTE,
    }


def progress_csv(data: dict) -> bytes:
    fields = [
        "user_id",
        "姓名",
        "邮箱",
        "用户组",
        "已完成活动数",
        "活动总数",
        "完成度(%)",
        "状态",
        "最近学习时间",
    ]
    rows = [
        {
            "user_id": r["user_id"],
            "姓名": r.get("name") or "",
            "邮箱": r.get("email") or "",
            "用户组": r.get("usergroup") or "",
            "已完成活动数": r["completed"],
            "活动总数": r["total_activities"],
            "完成度(%)": r["percentage"],
            "状态": r.get("status") or "",
            "最近学习时间": r.get("last_active_at") or "",
        }
        for r in data["students"]
    ]
    return csv_bytes(fields, rows)


async def build_recent(
    db_session: AsyncSession, org_id: int, days: int = 7, limit: int = 200
) -> dict:
    """最近 N 天组织里谁在学什么：完成/打开活动，以及新开始学的课程。

    `creation_date` 是文本列，跨库（Postgres / SQLite）没有统一的日期函数，
    所以按字符串前缀比较 —— 格式固定是 'YYYY-MM-DD HH:MM:SS.ffffff'，
    字典序和时间序一致，比较是安全的。
    """
    days = max(1, min(int(days), 365))
    limit = max(1, min(int(limit), ROW_LIMIT))
    since_naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    since = since_naive.strftime("%Y-%m-%d %H:%M:%S")

    step_result = await db_session.execute(
        select(TrailStep)
        .where(TrailStep.org_id == org_id)
        .where(TrailStep.creation_date >= since)  # type: ignore[operator]
        .order_by(TrailStep.creation_date.desc())  # type: ignore[union-attr]
        .limit(limit)
    )
    steps = list(step_result.scalars().all())

    run_result = await db_session.execute(
        select(TrailRun)
        .where(TrailRun.org_id == org_id)
        .where(TrailRun.creation_date >= since)  # type: ignore[operator]
        .order_by(TrailRun.creation_date.desc())  # type: ignore[union-attr]
        .limit(limit)
    )
    runs = list(run_result.scalars().all())

    course_ids = {s.course_id for s in steps} | {r.course_id for r in runs}
    courses = {}
    if course_ids:
        result = await db_session.execute(select(Course).where(Course.id.in_(course_ids)))  # type: ignore[union-attr]
        courses = {c.id: c for c in result.scalars().all()}

    activity_ids = {s.activity_id for s in steps}
    activities = {}
    if activity_ids:
        result = await db_session.execute(
            select(Activity).where(Activity.id.in_(activity_ids))  # type: ignore[union-attr]
        )
        activities = {a.id: a for a in result.scalars().all()}

    people = await users_by_id(
        db_session, sorted({s.user_id for s in steps} | {r.user_id for r in runs})
    )

    def _who(user_id: int) -> dict:
        user = people.get(user_id)
        return {
            "user_id": user_id,
            "user_uuid": user.user_uuid if user else None,
            "name": display_name(user) if user else None,
            "email": user.email if user else None,
        }

    events = []
    for step in steps:
        course = courses.get(step.course_id)
        activity = activities.get(step.activity_id)
        event = _who(step.user_id)
        event.update(
            {
                "kind": "activity_completed" if step.complete else "activity_opened",
                "at": to_iso(step.creation_date),
                "course_uuid": course.course_uuid if course else None,
                "course_name": course.name if course else None,
                "activity_uuid": activity.activity_uuid if activity else None,
                "activity_name": activity.name if activity else None,
            }
        )
        events.append(event)
    for run in runs:
        course = courses.get(run.course_id)
        event = _who(run.user_id)
        event.update(
            {
                "kind": "course_started",
                "at": to_iso(run.creation_date),
                "course_uuid": course.course_uuid if course else None,
                "course_name": course.name if course else None,
                "status": getattr(run.status, "value", run.status),
            }
        )
        events.append(event)

    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    events = events[:limit]

    out = {
        "org_id": org_id,
        "days": days,
        "since": to_iso(since),
        "event_count": len(events),
        "active_learner_count": len({e["user_id"] for e in events}),
        "events": events,
    }
    if not events:
        out["note"] = "最近 %d 天没有任何学习记录，可以把天数放大再看。" % days
    return out
