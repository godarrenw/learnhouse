# -*- coding: utf-8 -*-
"""成绩册与缺交名单。

移植自 learnhouse-agent/skill/learnhouse/progress.py 的 `gradebook()` 与
`missing_students()`，口径完全一致：

- 学生集合 = 绑定这门课的用户组成员 ∪ 有提交记录的人
- 单元格状态用「提交状态 + 截止时刻」自己算，规则和服务端 `_is_assignment_past_due()` 一致
- 分数走上游的 `compute_assignment_grade()`，所以百分比 / display_grade
  与学生在活动页里看到的完全相同
"""

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentUserSubmission,
)
from src.services.courses.activities.assignments import compute_assignment_grade
from src.services.ext.learning.common import (
    NOT_SUBMITTED_STATUSES,
    ROW_LIMIT,
    LearningError,
    csv_bytes,
    display_name,
    due_cutoff,
    parse_naive,
    roster,
    to_iso,
    users_by_id,
)

# 状态文案。前端会按 status_code 上色，status 是给 CSV 和无 i18n 场景用的中文。
STATUS_NOT_SUBMITTED = "未交"
STATUS_GRADED = "已批"
STATUS_UNGRADED = "待批"


def _cell_status(submission, cutoff) -> tuple[str, str, bool]:
    """把一条提交记录折成 (status_code, 中文状态, 是否迟交)。

    服务端**从不**主动写 LATE：过了截止时刻的提交直接被 403 拒掉。所以「迟交」
    只可能出现在老师事后延长截止日期的场合，这里靠提交时间 vs 截止时刻自己算。
    """
    if submission is None:
        return "not_submitted", STATUS_NOT_SUBMITTED, False
    raw_status = getattr(submission.submission_status, "value", submission.submission_status)
    if raw_status in NOT_SUBMITTED_STATUSES:
        return "not_submitted", STATUS_NOT_SUBMITTED, False
    late = raw_status == "LATE"
    if not late and cutoff:
        made = parse_naive(submission.creation_date)
        if made and made >= cutoff:
            late = True
    if raw_status == "GRADED":
        code, label = "graded", STATUS_GRADED
    else:
        code, label = "submitted", STATUS_UNGRADED
    if late:
        code = code + "_late"
        label = label + "·迟交"
    return code, label, late


async def _course_assignments(db_session: AsyncSession, course_id: int) -> list[Assignment]:
    result = await db_session.execute(
        select(Assignment)
        .where(Assignment.course_id == course_id)
        .order_by(Assignment.id)  # type: ignore[arg-type]
        .limit(ROW_LIMIT)
    )
    return list(result.scalars().all())


async def _max_grades(db_session: AsyncSession, assignment_ids: list[int]) -> dict[int, int]:
    """每份作业的满分 = 它所有题目的 max_grade_value 之和。

    和上游 `get_grade_assignment_submission()` 一样在读的时候现算，
    这样老师改了题目分值立刻生效。
    """
    if not assignment_ids:
        return {}
    result = await db_session.execute(
        select(AssignmentTask).where(AssignmentTask.assignment_id.in_(assignment_ids))  # type: ignore[union-attr]
    )
    totals: dict[int, int] = {aid: 0 for aid in assignment_ids}
    for task in result.scalars().all():
        totals[task.assignment_id] = totals.get(task.assignment_id, 0) + int(
            task.max_grade_value or 0
        )
    return totals


async def _submissions_by_assignment(
    db_session: AsyncSession, assignment_ids: list[int]
) -> dict[int, dict[int, AssignmentUserSubmission]]:
    if not assignment_ids:
        return {}
    result = await db_session.execute(
        select(AssignmentUserSubmission)
        .where(AssignmentUserSubmission.assignment_id.in_(assignment_ids))  # type: ignore[union-attr]
        .limit(ROW_LIMIT)
    )
    out: dict[int, dict[int, AssignmentUserSubmission]] = {aid: {} for aid in assignment_ids}
    for sub in result.scalars().all():
        out.setdefault(sub.assignment_id, {})[sub.user_id] = sub
    return out


async def build_gradebook(db_session: AsyncSession, course) -> dict:
    """成绩册矩阵：学生 × 该课程所有作业。

    单元格同时给原始分 `score` 和百分比 `percentage`，前端自己选一个显示 ——
    跨作业只有百分比可比（各作业满分不一致时求原始分平均没有意义），
    所以行尾同时给 `total_score`（原始分之和）与 `average_percentage`。
    """
    assignments = await _course_assignments(db_session, course.id)
    assignment_ids = [a.id for a in assignments if a.id is not None]
    max_grades = await _max_grades(db_session, assignment_ids)
    subs_by_assignment = await _submissions_by_assignment(db_session, assignment_ids)

    students, groups = await roster(db_session, course.course_uuid, course.org_id)

    # 组外但交过作业的人也要出现在成绩册里
    extra_ids = sorted(
        {
            uid
            for by_user in subs_by_assignment.values()
            for uid in by_user
            if uid not in students
        }
    )
    for uid, user in (await users_by_id(db_session, extra_ids)).items():
        students[uid] = {
            "user_id": uid,
            "user_uuid": user.user_uuid,
            "name": display_name(user),
            "email": user.email,
            "usergroup": "（组外，有提交）",
        }

    columns = [
        {
            "assignment_uuid": a.assignment_uuid,
            "title": a.title,
            "due_date": a.due_date,
            "published": bool(a.published),
            "ungraded": bool(a.ungraded),
            "max_grade": max_grades.get(a.id, 0),
        }
        for a in assignments
    ]
    cutoffs = {a.id: due_cutoff(a.due_date) for a in assignments}

    rows = []
    for uid in sorted(students):
        row = dict(students[uid])
        cells, raw_total, percentages, submitted = [], 0, [], 0
        for assignment in assignments:
            sub = subs_by_assignment.get(assignment.id, {}).get(uid)
            status_code, status_label, late = _cell_status(sub, cutoffs[assignment.id])
            cell = {
                "assignment_uuid": assignment.assignment_uuid,
                "title": assignment.title,
                "status_code": status_code,
                "status": status_label,
                "late": late,
                "score": None,
                "max_grade": max_grades.get(assignment.id, 0),
                "percentage": None,
                "display_grade": None,
                "submitted_at": None,
            }
            if status_code != "not_submitted" and sub is not None:
                submitted += 1
                cell["submitted_at"] = to_iso(sub.creation_date)
                if assignment.ungraded:
                    # 形成性作业没有分数，给个 0 会被读成「不及格」，所以留空
                    cell["display_grade"] = "不计分"
                else:
                    computed = compute_assignment_grade(
                        int(sub.grade or 0),
                        max_grades.get(assignment.id, 0),
                        assignment.grading_type,
                        sub.overall_feedback,
                        assignment.pass_threshold_percentage,
                    )
                    cell["score"] = computed["grade"]
                    cell["max_grade"] = computed["max_grade"]
                    cell["percentage"] = computed["percentage"]
                    cell["display_grade"] = computed["display_grade"]
                    raw_total += computed["grade"]
                    percentages.append(computed["percentage"])
            cells.append(cell)
        row["cells"] = cells
        row["submitted"] = submitted
        row["assignment_total"] = len(assignments)
        row["total_score"] = raw_total
        row["average_percentage"] = (
            round(sum(percentages) / len(percentages), 2) if percentages else None
        )
        rows.append(row)

    out = {
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "usergroups": groups,
        "assignment_count": len(assignments),
        "student_count": len(rows),
        "assignments": columns,
        "students": rows,
    }
    if not groups:
        out["note"] = (
            "这门课没有绑定任何用户组，成绩册里只有交过作业的人。"
            "要按班级名单出完整成绩册，先在「用户组」里建组并把这门课挂上去。"
        )
    return out


def gradebook_csv(data: dict) -> bytes:
    """成绩册 CSV。列名沿用 skill 版本，老师拿到的表和以前一样。"""
    fields = ["user_id", "姓名", "邮箱", "用户组"]
    for column in data["assignments"]:
        name = column["title"] or column["assignment_uuid"]
        fields.append(name)
        fields.append("%s·百分比" % name)
        fields.append("%s·状态" % name)
    fields += ["已交份数", "作业总数", "总分", "平均百分比"]

    rows = []
    for student in data["students"]:
        row = {
            "user_id": student["user_id"],
            "姓名": student.get("name") or "",
            "邮箱": student.get("email") or "",
            "用户组": student.get("usergroup") or "",
            "已交份数": student["submitted"],
            "作业总数": student["assignment_total"],
            "总分": student["total_score"],
            "平均百分比": student["average_percentage"],
        }
        for column, cell in zip(data["assignments"], student["cells"]):
            name = column["title"] or column["assignment_uuid"]
            row[name] = "" if cell["score"] is None else cell["score"]
            row["%s·百分比" % name] = (
                "" if cell["percentage"] is None else cell["percentage"]
            )
            row["%s·状态" % name] = cell["status"]
        rows.append(row)
    return csv_bytes(fields, rows)


async def build_missing(
    db_session: AsyncSession, course, assignment_uuid: str | None = None
) -> dict:
    """缺交名单：按绑定用户组的成员名单，对比每份作业的提交记录。

    没有绑定用户组时拿不到「应交名单」，返回空表并带 note 说明。
    """
    assignments = await _course_assignments(db_session, course.id)
    if assignment_uuid:
        assignments = [a for a in assignments if a.assignment_uuid == assignment_uuid]
        if not assignments:
            raise LearningError("这门课里没有这份作业")

    assignment_ids = [a.id for a in assignments if a.id is not None]
    subs_by_assignment = await _submissions_by_assignment(db_session, assignment_ids)
    students, groups = await roster(db_session, course.course_uuid, course.org_id)

    rows = []
    for assignment in assignments:
        by_user = subs_by_assignment.get(assignment.id, {})
        for uid in sorted(students):
            sub = by_user.get(uid)
            status_code, status_label, _late = _cell_status(sub, None)
            if status_code != "not_submitted":
                continue
            row = dict(students[uid])
            row.update(
                {
                    "assignment_uuid": assignment.assignment_uuid,
                    "assignment": assignment.title,
                    "due_date": assignment.due_date,
                    "status_code": status_code,
                    "status": status_label,
                }
            )
            rows.append(row)

    out = {
        "course_uuid": course.course_uuid,
        "course_name": course.name,
        "usergroups": groups,
        "roster_size": len(students),
        "assignment_count": len(assignments),
        "missing_count": len(rows),
        "assignments": [
            {
                "assignment_uuid": a.assignment_uuid,
                "title": a.title,
                "due_date": a.due_date,
                "published": bool(a.published),
            }
            for a in assignments
        ],
        "missing": rows,
    }
    if not groups:
        out["note"] = (
            "这门课没有绑定任何用户组，拿不到「应交名单」，所以判断不了谁没交。"
            "先在「用户组」里建组并把这门课挂上去。"
        )
    return out


def missing_csv(data: dict) -> bytes:
    fields = ["user_id", "姓名", "邮箱", "用户组", "作业", "截止日期", "状态"]
    rows = [
        {
            "user_id": r["user_id"],
            "姓名": r.get("name") or "",
            "邮箱": r.get("email") or "",
            "用户组": r.get("usergroup") or "",
            "作业": r.get("assignment") or "",
            "截止日期": r.get("due_date") or "",
            "状态": r.get("status") or "",
        }
        for r in data["missing"]
    ]
    return csv_bytes(fields, rows)
