"""随堂测：一条请求建一份小测，以及每题答对率与名单。

移植自 skill/learnhouse/tools.py 的 `quick_quiz` / `quiz_results` /
`_quiz_question_stats`。答对率是**本地按题目答案和学生提交算的**，不依赖服务端
的判分结果 —— 形成性作业（ungraded）本来就不走判分，不能赌它。
文件题和代码题标成「需人工」，不进答对率统计。
"""

import re
from datetime import date

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentTaskSubmission,
    AssignmentUserSubmission,
)
from src.db.courses.courses import Course
from src.db.users import PublicUser, User
from src.security.rbac import AccessAction, check_resource_access

from .create import create_from_spec
from .spec import TYPE_TO_KIND, SpecError

MANUAL_KINDS = ("file", "code")


async def create_quick_quiz(
    request: Request,
    course_uuid: str,
    chapter_id: int,
    title: str,
    questions: list[dict],
    current_user: PublicUser,
    db_session: AsyncSession,
    formative: bool = True,
    publish: bool = False,
    due_date: str | None = None,
    description: str = "",
) -> dict:
    """建一份随堂小测。

    默认是**形成性**（ungraded，不计入成绩）且**交卷即公布答案**
    （solution_reveal=ON_SUBMISSION），这正是随堂测的用法：当堂知道对错。
    formative=False 会切回计分作业，答案默认不公布。
    """
    if not questions:
        raise SpecError("随堂测至少要有一道题")
    if not (title or "").strip():
        raise SpecError("缺标题")

    if due_date and str(due_date).strip().lower() in ("today", "今天"):
        due_date = date.today().isoformat()

    full_spec: dict = {
        "name": title.strip(),
        "description": description or "随堂小测",
        "tasks": questions,
        "publish": bool(publish),
        "grading_type": "NUMERIC",
        "auto_grading": True,
        "formative": bool(formative),
        # 形成性测验的意义就是当堂看到对错，所以交卷即给答案
        "show_correct_answers": bool(formative),
        "solution_reveal": "ON_SUBMISSION" if formative else "NEVER",
        "allow_retries": bool(formative),
    }
    if due_date:
        full_spec["due_date"] = str(due_date)[:10]

    made = await create_from_spec(
        request, course_uuid, chapter_id, full_spec, current_user, db_session,
        publish_override=bool(publish),
    )
    made["formative"] = bool(formative)
    made["due_date"] = full_spec.get("due_date")
    return made


# ---------------------------------------------------------------- 结果统计


def question_stats(task_type: str, contents: dict, task_title: str, submission) -> list[tuple]:
    """算一份提交在某一道题上的对错，返回 [(题面, True/False/None)]。

    None 表示这一题没法自动判（文件题、代码题，或者学生没交）。
    """
    kind = TYPE_TO_KIND.get(task_type)
    contents = contents or {}
    ans = submission
    # 题面优先用题干（prompt），没有才退回 task 标题
    label = contents.get("prompt") or task_title or kind or ""

    if kind == "quiz":
        picked = {}
        for s in ((ans or {}).get("submissions") or []):
            picked[(s.get("questionUUID"), s.get("optionUUID"))] = bool(s.get("answer"))
        out = []
        for q in contents.get("questions") or []:
            text = q.get("questionText") or label
            if not ans:
                out.append((text, None))
                continue
            ok = True
            for o in q.get("options") or []:
                chosen = picked.get((q.get("questionUUID"), o.get("optionUUID")), False)
                if chosen != bool(o.get("assigned_right_answer")):
                    ok = False
                    break
            out.append((text, ok))
        return out

    if kind == "form":
        filled = {
            s.get("blankUUID"): s.get("answer")
            for s in ((ans or {}).get("submissions") or [])
        }
        out = []
        for q in contents.get("questions") or []:
            text = q.get("questionText") or label
            if not ans:
                out.append((text, None))
                continue
            ok = all(
                str(filled.get(b.get("blankUUID"), "")).strip().lower()
                == str(b.get("correctAnswer", "")).strip().lower()
                for b in (q.get("blanks") or [])
            )
            out.append((text, ok))
        return out

    if kind == "short_answer":
        if not ans:
            return [(label, None)]
        given = str((ans or {}).get("answer", "")).strip()
        mode = contents.get("match_mode", "case_insensitive")
        oks = []
        for a in contents.get("correct_answers") or []:
            a = str(a)
            if mode == "exact":
                oks.append(given == a)
            elif mode == "contains":
                oks.append(a.lower() in given.lower())
            elif mode == "regex":
                try:
                    oks.append(bool(re.search(a, given)))
                except re.error:
                    oks.append(False)
            else:
                oks.append(given.lower() == a.lower())
        return [(label, any(oks))]

    if kind == "number_answer":
        if not ans:
            return [(label, None)]
        try:
            given = float((ans or {}).get("answer"))
        except (TypeError, ValueError):
            return [(label, False)]
        try:
            target = float(contents.get("correct_value", 0))
            tol = float(contents.get("tolerance", 0) or 0)
        except (TypeError, ValueError):
            return [(label, None)]
        return [(label, abs(given - target) <= tol)]

    # file / code：得人工看
    return [(label, None)]


async def _load_assignment(
    request: Request,
    assignment_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
    action: AccessAction = AccessAction.UPDATE,
) -> tuple[Assignment, Course]:
    assignment = (await db_session.execute(
        select(Assignment).where(Assignment.assignment_uuid == assignment_uuid)
    )).scalars().first()
    if not assignment:
        raise HTTPException(status_code=404, detail="作业不存在")
    course = (await db_session.execute(
        select(Course).where(Course.id == assignment.course_id)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    await check_resource_access(request, db_session, current_user, course.course_uuid, action)
    return assignment, course


def _display_name(user: User | None, user_id: int) -> str:
    if user is None:
        return str(user_id)
    full = " ".join(p for p in [user.first_name or "", user.last_name or ""] if p).strip()
    return full or user.username or user.email or str(user_id)


async def quiz_results(
    request: Request,
    assignment_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
) -> dict:
    """随堂测结果：谁交了、每道题的答对率。"""
    assignment, course = await _load_assignment(
        request, assignment_uuid, current_user, db_session
    )

    tasks = list((await db_session.execute(
        select(AssignmentTask)
        .where(AssignmentTask.assignment_id == assignment.id)
        .order_by(AssignmentTask.id)
    )).scalars().all())

    rows = (await db_session.execute(
        select(AssignmentUserSubmission, User)
        .outerjoin(User, AssignmentUserSubmission.user_id == User.id)
        .where(AssignmentUserSubmission.assignment_id == assignment.id)
        .order_by(AssignmentUserSubmission.id)
    )).all()

    task_ids = [t.id for t in tasks]
    task_subs: dict[tuple[int, int], dict] = {}
    if task_ids:
        for ts in (await db_session.execute(
            select(AssignmentTaskSubmission)
            .where(AssignmentTaskSubmission.assignment_task_id.in_(task_ids))
        )).scalars().all():
            task_subs[(ts.user_id, ts.assignment_task_id)] = ts.task_submission

    # 题面清单（一道 task 可能含多个小问）
    question_labels = []
    for t in tasks:
        kind = TYPE_TO_KIND.get(
            t.assignment_type.value
            if hasattr(t.assignment_type, "value")
            else t.assignment_type
        )
        for text, _ in question_stats(
            t.assignment_type.value if hasattr(t.assignment_type, "value") else t.assignment_type,
            t.contents, t.title, None,
        ):
            question_labels.append({
                "task_uuid": t.assignment_task_uuid,
                "task_title": t.title,
                "question": text,
                "kind": kind,
            })
    tally = [{"right": 0, "wrong": 0, "blank": 0} for _ in question_labels]

    students = []
    for user_submission, user in rows:
        row = {
            "user_id": user_submission.user_id,
            "name": _display_name(user, user_submission.user_id),
            "email": user.email if user else None,
            "status": (
                user_submission.submission_status.value
                if hasattr(user_submission.submission_status, "value")
                else user_submission.submission_status
            ),
            "answers": [],
        }
        idx = 0
        right = total = 0
        for t in tasks:
            atype = (
                t.assignment_type.value
                if hasattr(t.assignment_type, "value")
                else t.assignment_type
            )
            payload = task_subs.get((user_submission.user_id, t.id))
            for text, ok in question_stats(atype, t.contents, t.title, payload):
                row["answers"].append({"question": text, "correct": ok})
                if ok is True:
                    tally[idx]["right"] += 1
                    right += 1
                    total += 1
                elif ok is False:
                    tally[idx]["wrong"] += 1
                    total += 1
                else:
                    tally[idx]["blank"] += 1
                idx += 1
        row["correct"] = right
        row["auto_gradable"] = total
        row["score_percent"] = round(right * 100.0 / total, 1) if total else None
        students.append(row)

    per_question = []
    for label, t in zip(question_labels, tally):
        answered = t["right"] + t["wrong"]
        per_question.append({
            **label,
            "right": t["right"], "wrong": t["wrong"], "no_answer": t["blank"],
            "correct_rate": round(t["right"] * 100.0 / answered, 1) if answered else None,
            "manual_only": label["kind"] in MANUAL_KINDS,
        })

    submitted = [s for s in students if s["status"] not in (None, "NOT_SUBMITTED", "PENDING")]
    return {
        "assignment_uuid": assignment.assignment_uuid,
        "title": assignment.title,
        "course_uuid": course.course_uuid,
        "formative": bool(assignment.ungraded),
        "submitted_count": len(submitted),
        "roster_count": len(students),
        "per_question": per_question,
        "students": students,
    }
