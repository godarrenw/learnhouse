# -*- coding: utf-8 -*-
"""学情工具（成绩册 / 缺交 / 学习进度 / 课程体检）的接口与服务层测试。

本地预发库里数据太少，这里的数据全部由测试自己造，跑在 conftest 的
内存 SQLite 上，复用 org / course / chapter / activity / admin_user 等现成 fixture。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.core.events.database import get_db_session
from src.db.courses.activities import (
    Activity,
    ActivitySubTypeEnum,
    ActivityTypeEnum,
)
from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentTaskTypeEnum,
    AssignmentUserSubmission,
    AssignmentUserSubmissionStatus,
    GradingTypeEnum,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.trail_runs import TrailRun
from src.db.trail_steps import TrailStep
from src.db.trails import Trail
from src.db.usergroup_resources import UserGroupResource
from src.db.usergroup_user import UserGroupUser
from src.db.usergroups import UserGroup
from src.db.users import User
from src.routers.ext.deps import require_teacher
from src.routers.ext.learning import router as learning_router
from src.services.ext.learning.common import to_iso
from src.services.ext.learning.gradebook import (
    build_gradebook,
    build_missing,
    gradebook_csv,
)
from src.services.ext.learning.lint import fix_publish, lint_course
from src.services.ext.learning.progress import (
    build_progress,
    build_recent,
    build_student_progress,
)

NOW = str(datetime.now())


# ---------------------------------------------------------------------------
# 造数据
# ---------------------------------------------------------------------------


@pytest.fixture
async def students(db, org):
    """两名学生，都在同一个用户组里，组绑定了测试课程。"""
    people = []
    for index, (name, email) in enumerate(
        [("Zhang", "zhang@test.com"), ("Li", "li@test.com")], start=10
    ):
        user = User(
            id=index,
            username="stu%d" % index,
            first_name=name,
            last_name="Student",
            email=email,
            password="hashed",
            user_uuid="user_stu%d" % index,
            creation_date=NOW,
            update_date=NOW,
        )
        db.add(user)
        people.append(user)
    await db.commit()
    for user in people:
        await db.refresh(user)
    return people


@pytest.fixture
async def usergroup(db, org, course, students):
    group = UserGroup(
        id=1,
        name="2026 春季班",
        description="测试班级",
        org_id=org.id,
        usergroup_uuid="ug_test",
        creation_date=NOW,
        update_date=NOW,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    db.add(
        UserGroupResource(
            usergroup_id=group.id,
            resource_uuid=course.course_uuid,
            org_id=org.id,
            creation_date=NOW,
            update_date=NOW,
        )
    )
    for user in students:
        db.add(
            UserGroupUser(
                usergroup_id=group.id,
                user_id=user.id,
                org_id=org.id,
                creation_date=NOW,
                update_date=NOW,
            )
        )
    await db.commit()
    return group


@pytest.fixture
async def assignment(db, org, course, chapter, activity):
    """一份 100 分的作业（两道题各 50 分），挂在测试活动上。"""
    record = Assignment(
        id=1,
        title="第一次作业",
        description="测试作业",
        due_date="2026-01-31",
        published=True,
        grading_type=GradingTypeEnum.NUMERIC,
        org_id=org.id,
        course_id=course.id,
        chapter_id=chapter.id,
        activity_id=activity.id,
        assignment_uuid="assignment_test",
        creation_date=NOW,
        update_date=NOW,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    for task_index in (1, 2):
        db.add(
            AssignmentTask(
                id=task_index,
                title="第 %d 题" % task_index,
                description="",
                hint="",
                contents={},
                max_grade_value=50,
                assignment_type=AssignmentTaskTypeEnum.QUIZ,
                assignment_id=record.id,
                org_id=org.id,
                course_id=course.id,
                chapter_id=chapter.id,
                activity_id=activity.id,
                assignment_task_uuid="task_%d" % task_index,
                creation_date=NOW,
                update_date=NOW,
            )
        )
    await db.commit()
    return record


@pytest.fixture
async def submission(db, assignment, students):
    """只有第一名学生交了并被批了 80 分，第二名一直没交。"""
    row = AssignmentUserSubmission(
        id=1,
        submission_status=AssignmentUserSubmissionStatus.GRADED,
        grade=80,
        overall_feedback="不错",
        attempt_number=1,
        user_id=students[0].id,
        assignment_id=assignment.id,
        assignmentusersubmission_uuid="aus_test",
        creation_date="2026-01-20 03:00:00.000000",
        update_date="2026-01-20 03:00:00.000000",
    )
    db.add(row)
    await db.commit()
    return row


@pytest.fixture
async def trail_data(db, org, course, activity, students):
    """第一名学生完成了唯一那个活动，第二名只开了课程没完成任何活动。"""
    trail = Trail(
        id=1,
        org_id=org.id,
        user_id=students[0].id,
        trail_uuid="trail_1",
        creation_date=NOW,
        update_date=NOW,
    )
    db.add(trail)
    await db.commit()
    await db.refresh(trail)

    recent = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S.%f")
    for index, user in enumerate(students, start=1):
        db.add(
            TrailRun(
                id=index,
                trail_id=trail.id,
                course_id=course.id,
                org_id=org.id,
                user_id=user.id,
                creation_date=recent,
                update_date=recent,
            )
        )
    db.add(
        TrailStep(
            id=1,
            complete=True,
            teacher_verified=False,
            grade="",
            trailrun_id=1,
            trail_id=trail.id,
            activity_id=activity.id,
            course_id=course.id,
            org_id=org.id,
            user_id=students[0].id,
            creation_date=recent,
            update_date=recent,
        )
    )
    await db.commit()
    return trail


# ---------------------------------------------------------------------------
# 成绩册
# ---------------------------------------------------------------------------


async def test_gradebook_matrix(db, course, usergroup, assignment, submission, students):
    data = await build_gradebook(db, course)

    assert data["student_count"] == 2
    assert data["assignment_count"] == 1
    assert data["assignments"][0]["max_grade"] == 100

    graded = next(s for s in data["students"] if s["user_id"] == students[0].id)
    assert graded["cells"][0]["status_code"] == "graded"
    assert graded["cells"][0]["score"] == 80
    assert graded["cells"][0]["percentage"] == 80.0
    assert graded["total_score"] == 80
    assert graded["average_percentage"] == 80.0
    assert graded["usergroup"] == "2026 春季班"

    absent = next(s for s in data["students"] if s["user_id"] == students[1].id)
    assert absent["cells"][0]["status_code"] == "not_submitted"
    assert absent["cells"][0]["score"] is None
    assert absent["submitted"] == 0


async def test_gradebook_without_usergroup_has_note(db, course, assignment, submission):
    """没绑用户组时，成绩册只剩有提交的人，并且必须带 note 说明。"""
    data = await build_gradebook(db, course)
    assert data["student_count"] == 1
    assert data["students"][0]["usergroup"] == "（组外，有提交）"
    assert "没有绑定任何用户组" in data["note"]


async def test_gradebook_csv_has_bom(db, course, usergroup, assignment, submission):
    payload = gradebook_csv(await build_gradebook(db, course))
    assert payload.startswith(b"\xef\xbb\xbf")
    text = payload.decode("utf-8-sig")
    assert "姓名" in text.splitlines()[0]
    assert "第一次作业·状态" in text.splitlines()[0]


async def test_late_submission_flagged(db, course, usergroup, assignment, students):
    """截止日期当天整天算按时，第二天才算迟交（和服务端同一套规则）。"""
    db.add(
        AssignmentUserSubmission(
            id=2,
            submission_status=AssignmentUserSubmissionStatus.SUBMITTED,
            grade=0,
            attempt_number=1,
            user_id=students[1].id,
            assignment_id=assignment.id,
            assignmentusersubmission_uuid="aus_late",
            creation_date="2026-02-01 10:00:00.000000",
            update_date="2026-02-01 10:00:00.000000",
        )
    )
    await db.commit()
    data = await build_gradebook(db, course)
    late = next(s for s in data["students"] if s["user_id"] == students[1].id)
    assert late["cells"][0]["late"] is True
    assert late["cells"][0]["status_code"] == "submitted_late"


# ---------------------------------------------------------------------------
# 缺交名单
# ---------------------------------------------------------------------------


async def test_missing_lists_only_non_submitters(
    db, course, usergroup, assignment, submission, students
):
    data = await build_missing(db, course)
    assert data["roster_size"] == 2
    assert data["missing_count"] == 1
    assert data["missing"][0]["user_id"] == students[1].id
    assert data["missing"][0]["assignment"] == "第一次作业"


async def test_missing_rejects_foreign_assignment(db, course, usergroup, assignment):
    with pytest.raises(Exception) as excinfo:
        await build_missing(db, course, assignment_uuid="not_in_this_course")
    assert "没有这份作业" in str(excinfo.value.detail)


# ---------------------------------------------------------------------------
# 学习进度
# ---------------------------------------------------------------------------


async def test_progress_uses_chapteractivity_denominator(
    db, course, usergroup, trail_data, students
):
    data = await build_progress(db, course)
    assert data["total_activities"] == 1

    done = next(s for s in data["students"] if s["user_id"] == students[0].id)
    assert done["completed"] == 1
    assert done["percentage"] == 100.0
    assert done["last_active_at"].endswith("+08:00")

    idle = next(s for s in data["students"] if s["user_id"] == students[1].id)
    assert idle["completed"] == 0
    assert idle["percentage"] == 0.0
    assert idle["has_started"] is True


async def test_progress_counts_unpublished_activities(
    db, org, course, chapter, usergroup, trail_data
):
    """分母含未发布活动 —— 加一个未发布活动，分母要变成 2。"""
    extra = Activity(
        id=99,
        name="草稿活动",
        activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
        content={"type": "doc", "content": []},
        published=False,
        org_id=org.id,
        course_id=course.id,
        activity_uuid="activity_draft",
        creation_date=NOW,
        update_date=NOW,
    )
    db.add(extra)
    await db.commit()
    db.add(
        ChapterActivity(
            order=2,
            chapter_id=chapter.id,
            activity_id=extra.id,
            course_id=course.id,
            org_id=org.id,
            creation_date=NOW,
            update_date=NOW,
        )
    )
    await db.commit()
    data = await build_progress(db, course)
    assert data["total_activities"] == 2


async def test_student_progress_detail(db, course, usergroup, trail_data, students):
    data = await build_student_progress(db, course, students[0].user_uuid)
    assert data["completed"] == 1
    assert len(data["steps"]) == 1
    step = data["steps"][0]
    assert step["activity_name"] == "Test Activity"
    assert step["chapter"] == "Test Chapter"
    assert step["complete"] is True
    assert step["completed_at"].endswith("+08:00")


async def test_student_progress_unknown_student(db, course):
    with pytest.raises(Exception) as excinfo:
        await build_student_progress(db, course, "user_does_not_exist")
    assert excinfo.value.status_code == 404


async def test_recent_events(db, org, course, trail_data, students):
    data = await build_recent(db, org.id, days=7)
    assert data["event_count"] >= 3
    assert data["active_learner_count"] == 2
    kinds = {e["kind"] for e in data["events"]}
    assert "course_started" in kinds
    assert "activity_completed" in kinds


async def test_recent_is_org_scoped(db, other_org, trail_data):
    data = await build_recent(db, other_org.id, days=7)
    assert data["event_count"] == 0
    assert "没有任何学习记录" in data["note"]


def test_display_name_skips_space_between_cjk_parts():
    """中文姓名不该被拼成「张 小明」。"""
    from src.db.users import User as UserModel
    from src.services.ext.learning.common import display_name

    def make(first, last, username="u"):
        return UserModel(
            username=username, first_name=first, last_name=last,
            email="x@example.com", password="x", user_uuid="u",
            creation_date=NOW, update_date=NOW,
        )

    assert display_name(make("张", "小明")) == "张小明"
    assert display_name(make("Ada", "Lovelace")) == "Ada Lovelace"
    assert display_name(make("", "", username="fallback")) == "fallback"


def test_to_iso_converts_utc_to_display_timezone():
    assert to_iso("2026-09-08 11:30:31.402905").startswith("2026-09-08T19:30:31")
    assert to_iso("") is None
    assert to_iso("垃圾数据") is None


# ---------------------------------------------------------------------------
# 课程体检
# ---------------------------------------------------------------------------


async def test_lint_reports_empty_page(db, course, usergroup, activity):
    report = await lint_course(db, course)
    codes = {f["code"] for f in report["findings"]}
    assert "empty_page" in codes
    assert report["counts"]["error"] >= 1
    empty = next(f for f in report["findings"] if f["code"] == "empty_page")
    assert empty["target_uuid"] == activity.activity_uuid
    assert empty["fix_hint"]


async def test_lint_reports_private_course_without_group(db, course, activity):
    course.public = False
    db.add(course)
    await db.commit()
    report = await lint_course(db, course)
    codes = {f["code"] for f in report["findings"]}
    assert "private_without_group" in codes


async def test_lint_reports_unpublished_activity_and_assignment_issues(
    db, org, course, chapter, activity
):
    """作业壳没有题目要报 error；活动未发布要报 warn 且可一键修。"""
    activity.published = False
    db.add(activity)
    await db.commit()

    shell = Activity(
        id=60,
        name="作业壳",
        activity_type=ActivityTypeEnum.TYPE_ASSIGNMENT,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_ASSIGNMENT_ANY,
        content={},
        published=True,
        org_id=org.id,
        course_id=course.id,
        activity_uuid="activity_assignment",
        creation_date=NOW,
        update_date=NOW,
    )
    db.add(shell)
    await db.commit()
    db.add(
        ChapterActivity(
            order=3,
            chapter_id=chapter.id,
            activity_id=shell.id,
            course_id=course.id,
            org_id=org.id,
            creation_date=NOW,
            update_date=NOW,
        )
    )
    await db.commit()

    # 还没有作业记录 —— 学生点进去是空的
    report = await lint_course(db, course)
    codes = {f["code"] for f in report["findings"]}
    assert "unpublished_activity" in codes
    assert "assignment_shell_without_record" in codes
    assert report["fixable_count"] == 1

    # 补上作业记录但一道题都没有
    db.add(
        Assignment(
            id=5,
            title="空作业",
            description="",
            due_date="2020-01-01",
            published=False,
            grading_type=GradingTypeEnum.NUMERIC,
            org_id=org.id,
            course_id=course.id,
            chapter_id=chapter.id,
            activity_id=shell.id,
            assignment_uuid="assignment_empty",
            creation_date=NOW,
            update_date=NOW,
        )
    )
    await db.commit()
    report = await lint_course(db, course)
    codes = {f["code"] for f in report["findings"]}
    assert "assignment_shell_without_record" not in codes
    assert "assignment_without_tasks" in codes
    assert "due_date_passed" in codes
    assert "assignment_unpublished" in codes


async def test_fix_publish_requires_confirm(db, course, activity):
    with pytest.raises(Exception) as excinfo:
        await fix_publish(db, course, confirm=False)
    assert "confirm" in str(excinfo.value.detail)


async def test_fix_publish_skips_activities_with_errors(db, org, course, chapter):
    """空页有 error，不能被一键发布出去；内容正常的才会发。"""
    broken = Activity(
        id=51,
        name="空页",
        activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
        content={"type": "doc", "content": []},
        published=False,
        org_id=org.id,
        course_id=course.id,
        activity_uuid="activity_broken",
        creation_date=NOW,
        update_date=NOW,
    )
    good = Activity(
        id=52,
        name="正常页",
        activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
        content={
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "有内容"}]}
            ],
        },
        published=False,
        org_id=org.id,
        course_id=course.id,
        activity_uuid="activity_good",
        creation_date=NOW,
        update_date=NOW,
    )
    db.add(broken)
    db.add(good)
    await db.commit()
    for order, item in enumerate([broken, good], start=1):
        db.add(
            ChapterActivity(
                order=order,
                chapter_id=chapter.id,
                activity_id=item.id,
                course_id=course.id,
                org_id=org.id,
                creation_date=NOW,
                update_date=NOW,
            )
        )
    await db.commit()

    result = await fix_publish(db, course, confirm=True)
    published = {row["activity_uuid"] for row in result["published"]}
    skipped = {row["activity_uuid"] for row in result["skipped"]}
    assert "activity_good" in published
    assert "activity_broken" in skipped


# ---------------------------------------------------------------------------
# 路由层：权限与 CSV
# ---------------------------------------------------------------------------


@pytest.fixture
def app(db, admin_user):
    application = FastAPI()
    application.include_router(learning_router, prefix="/api/v1/ext/learning")
    application.dependency_overrides[get_db_session] = lambda: db
    application.dependency_overrides[require_teacher] = lambda: admin_user
    yield application
    application.dependency_overrides.clear()


@pytest.fixture
def allow_course():
    """放行课程级权限检查，专测路由本身的行为。"""
    with patch(
        "src.routers.ext.learning.rbac_check_course", new_callable=AsyncMock
    ) as mock:
        yield mock


@pytest.fixture
def deny_course():
    """课程级权限检查抛 403，验证路由确实把它接在了前面。"""
    with patch(
        "src.routers.ext.learning.rbac_check_course",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=403, detail="no rights"),
    ) as mock:
        yield mock


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as async_client:
        yield async_client


async def test_route_gradebook_json(
    client, allow_course, course, usergroup, assignment, submission
):
    response = await client.get(
        "/api/v1/ext/learning/courses/%s/gradebook?org_id=1" % course.course_uuid
    )
    assert response.status_code == 200
    assert response.json()["student_count"] == 2


async def test_route_gradebook_csv(
    client, allow_course, course, usergroup, assignment, submission
):
    response = await client.get(
        "/api/v1/ext/learning/courses/%s/gradebook?org_id=1&format=csv" % course.course_uuid
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content.startswith(b"\xef\xbb\xbf")


async def test_route_unknown_course_404(client, allow_course):
    response = await client.get("/api/v1/ext/learning/courses/nope/gradebook?org_id=1")
    assert response.status_code == 404


async def test_route_lint_fix_publish_needs_confirm(client, allow_course, course, activity):
    response = await client.post(
        "/api/v1/ext/learning/courses/%s/lint/fix-publish?org_id=1" % course.course_uuid,
        json={},
    )
    assert response.status_code == 400


async def test_route_rejects_cross_org_course(client, allow_course, other_org, course):
    """拿别的组织的 org_id 来读这门课，按「找不到」处理。"""
    response = await client.get(
        "/api/v1/ext/learning/courses/%s/gradebook?org_id=%d"
        % (course.course_uuid, other_org.id)
    )
    assert response.status_code == 404


async def test_route_requires_org_id(client, allow_course, course):
    """require_teacher 把 org_id 声明成必填 query 参数，漏了要 422。"""
    response = await client.get(
        "/api/v1/ext/learning/courses/%s/gradebook" % course.course_uuid
    )
    assert response.status_code == 422


async def test_route_denies_user_without_course_rights(client, deny_course, course, usergroup):
    """课程级权限不通过时，成绩册必须 403。"""
    response = await client.get(
        "/api/v1/ext/learning/courses/%s/gradebook?org_id=1" % course.course_uuid
    )
    assert response.status_code == 403
