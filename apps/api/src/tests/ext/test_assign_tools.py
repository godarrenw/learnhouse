"""教学工具 · 作业工具的行为测试。

覆盖五个 Tab 的后端：AI 出题、随堂测、查重、学期复用、版本回滚。
LLM 调用全程 mock（只 patch `chat_completion` 这一个联网入口）；
RBAC 与用量统计按上游测试的惯例 patch 成 no-op，权限本身由上游自己的测试覆盖。
"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlmodel import select

from src.db.courses.activities import (
    Activity,
    ActivitySubTypeEnum,
    ActivityTypeEnum,
)
from src.db.courses.assignments import (
    Assignment,
    AssignmentTask,
    AssignmentTaskSubmission,
    AssignmentTaskTypeEnum,
    AssignmentUserSubmission,
    AssignmentUserSubmissionStatus,
    GradingTypeEnum,
)
from src.db.courses.chapter_activities import ChapterActivity
from src.db.users import User
from src.services.ext.assign_tools import clone as clone_svc
from src.services.ext.assign_tools import draft as draft_svc
from src.services.ext.assign_tools import llm as llm_mod
from src.services.ext.assign_tools import quickquiz as quiz_svc
from src.services.ext.assign_tools import similarity as sim_svc
from src.services.ext.assign_tools import versions as ver_svc
from src.services.ext.assign_tools.create import create_from_spec
from src.services.ext.assign_tools.spec import (
    SpecError,
    build_task_contents,
    spec_template,
    validate_spec,
)
from src.services.ext.assign_tools.tiptap import tiptap_to_markdown, tiptap_to_plain_text

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# 通用 patch
# ---------------------------------------------------------------------------

@pytest.fixture
def bypass_ext_rbac():
    """把各 service 里的 check_resource_access 换成 no-op。"""
    targets = [
        "src.services.ext.assign_tools.draft.check_resource_access",
        "src.services.ext.assign_tools.quickquiz.check_resource_access",
        "src.services.ext.assign_tools.clone.check_resource_access",
        "src.services.ext.assign_tools.versions.check_resource_access",
        "src.services.courses.activities.activities.check_resource_access",
        "src.services.courses.activities.assignments.check_resource_access",
        "src.services.courses.activities.versioning.check_resource_access",
    ]
    patchers = [patch(t, new_callable=AsyncMock) for t in targets]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


@pytest.fixture
def bypass_usage():
    """用量/套餐/webhook 检查在单测里全部放行。"""
    targets = [
        ("src.services.courses.activities.assignments.check_limits_with_usage", AsyncMock()),
        ("src.services.courses.activities.assignments.increase_feature_usage", AsyncMock()),
        ("src.services.courses.activities.versioning.check_feature_access", AsyncMock()),
        ("src.services.courses.activities.versioning.dispatch_webhooks", AsyncMock()),
    ]
    patchers = [patch(t, new=m) for t, m in targets]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# spec 校验（纯函数，不需要数据库）
# ---------------------------------------------------------------------------

_GOOD_SPEC = {
    "name": "第一章练习",
    "publish": False,
    "tasks": [
        {
            "kind": "quiz",
            "title": "单选",
            "questions": [
                {
                    "text": "CNC 的 C 指什么？",
                    "options": [
                        {"text": "计算机", "correct": True},
                        {"text": "控制", "correct": False},
                    ],
                }
            ],
        },
        {
            "kind": "short_answer",
            "prompt": "CNC 全称",
            "answers": ["计算机数控"],
            "match_mode": "contains",
        },
    ],
}


async def test_validate_spec_ok():
    r = validate_spec(_GOOD_SPEC)
    assert r["ok"] is True
    assert r["task_count"] == 2
    assert r["tasks"][0]["type"] == "QUIZ"
    # 单选：只标了一个正确答案
    assert r["tasks"][0]["contents"]["questions"][0]["response_type"] == "single"
    assert r["warnings"] == []


async def test_validate_spec_publish_true_warns():
    spec = dict(_GOOD_SPEC, publish=True)
    r = validate_spec(spec)
    assert any("学生立刻能看到" in w for w in r["warnings"])


async def test_validate_spec_missing_name():
    with pytest.raises(SpecError) as e:
        validate_spec({"tasks": _GOOD_SPEC["tasks"]})
    assert "name" in str(e.value)


async def test_validate_spec_on_submit_typo_gets_hint():
    """ON_SUBMIT 是常见笔误，上游枚举里只有 ON_SUBMISSION。"""
    with pytest.raises(SpecError) as e:
        validate_spec(dict(_GOOD_SPEC, solution_reveal="ON_SUBMIT"))
    assert "ON_SUBMISSION" in str(e.value)


async def test_validate_spec_bad_due_date():
    with pytest.raises(SpecError) as e:
        validate_spec(dict(_GOOD_SPEC, due_date="2026/01/01"))
    assert "YYYY-MM-DD" in str(e.value)


async def test_validate_spec_quiz_without_correct_answer():
    bad = {
        "name": "x",
        "tasks": [{
            "kind": "quiz",
            "questions": [{"text": "?", "options": [{"text": "A"}, {"text": "B"}]}],
        }],
    }
    with pytest.raises(SpecError) as e:
        validate_spec(bad)
    assert "正确答案" in str(e.value)


async def test_validate_spec_comments_are_ignored():
    spec = dict(_GOOD_SPEC)
    spec["_note"] = "这行是注释"
    assert validate_spec(spec)["ok"] is True


async def test_build_task_contents_multiple_choice_is_detected():
    c = build_task_contents("quiz", questions=[{
        "text": "多选",
        "options": [
            {"text": "A", "correct": True},
            {"text": "B", "correct": True},
            {"text": "C", "correct": False},
        ],
    }])
    assert c["questions"][0]["response_type"] == "multiple"


async def test_build_task_contents_number_requires_value():
    with pytest.raises(SpecError):
        build_task_contents("number_answer", prompt="?")


async def test_spec_template_roundtrips_through_validation():
    """模板本身必须是能过校验的，否则老师照着改一定出错。"""
    t = spec_template(["quiz", "short_answer", "number_answer", "form", "file"])
    assert validate_spec(t)["ok"] is True


# ---------------------------------------------------------------------------
# tiptap → 文本
# ---------------------------------------------------------------------------

_DOC = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "数控机床"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "CNC 是计算机数控。", "marks": [{"type": "bold"}]}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "控制系统"}]}]},
        ]},
        {"type": "unknownBlock"},
    ],
}


async def test_tiptap_to_markdown():
    md = tiptap_to_markdown(_DOC)
    assert "## 数控机床" in md
    assert "**CNC 是计算机数控。**" in md
    assert "- 控制系统" in md
    assert "<!-- unknownBlock -->" in md


async def test_tiptap_plain_text_drops_markup_and_comments():
    txt = tiptap_to_plain_text(_DOC)
    assert "数控机床" in txt
    assert "**" not in txt
    assert "unknownBlock" not in txt


async def test_tiptap_handles_junk():
    assert tiptap_to_markdown(None).strip() == ""
    assert tiptap_to_markdown({"content": [None, 3]}).strip() == ""


# ---------------------------------------------------------------------------
# 数据库夹具
# ---------------------------------------------------------------------------

@pytest.fixture
async def page_activity(db, org, course, chapter):
    """一个有正文的富文本内容页，给 AI 出题和版本回滚用。"""
    a = Activity(
        id=10,
        name="第一节 数控基础",
        activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
        content={"type": "doc", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "数控机床由控制系统、"
                                                                      "伺服驱动系统和机械本体三部分组成。"
                                                                      "CNC 的全称是计算机数控。"}]},
        ]},
        published=True,
        org_id=org.id,
        course_id=course.id,
        activity_uuid="activity_page",
        current_version=3,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    db.add(ChapterActivity(
        order=2, chapter_id=chapter.id, activity_id=a.id,
        course_id=course.id, org_id=org.id,
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    ))
    await db.commit()
    return a


async def _make_assignment(db, org, course, chapter, activity, *, title="作业一",
                           due_date=None, ungraded=False, aid=100):
    a = Assignment(
        id=aid,
        title=title,
        description="",
        due_date=due_date,
        published=True,
        grading_type=GradingTypeEnum.NUMERIC,
        ungraded=ungraded,
        org_id=org.id,
        course_id=course.id,
        chapter_id=chapter.id,
        activity_id=activity.id,
        assignment_uuid=f"assignment_{aid}",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


async def _make_task(db, org, course, chapter, activity, assignment, *, tid,
                     atype, contents, title="题目"):
    t = AssignmentTask(
        id=tid,
        title=title,
        description="",
        hint="",
        assignment_type=atype,
        contents=contents,
        max_grade_value=100,
        assignment_task_uuid=f"assignmenttask_{tid}",
        assignment_id=assignment.id,
        org_id=org.id,
        course_id=course.id,
        chapter_id=chapter.id,
        activity_id=activity.id,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


async def _make_student(db, uid, name):
    u = User(
        id=uid, username=f"stu{uid}", first_name=name, last_name="",
        email=f"stu{uid}@test.com", password="x", user_uuid=f"user_{uid}",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(u)
    await db.commit()
    return u


async def _submit(db, assignment, task, user_id, payload, sid):
    db.add(AssignmentUserSubmission(
        id=sid,
        submission_status=AssignmentUserSubmissionStatus.SUBMITTED,
        grade=0, user_id=user_id, assignment_id=assignment.id,
        assignmentusersubmission_uuid=f"assignmentusersubmission_{sid}",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    ))
    db.add(AssignmentTaskSubmission(
        id=sid,
        assignment_task_submission_uuid=f"sub_{sid}",
        task_submission=payload,
        grade=0,
        task_submission_grade_feedback="",
        assignment_type=task.assignment_type,
        user_id=user_id,
        activity_id=task.activity_id,
        course_id=task.course_id,
        chapter_id=task.chapter_id,
        assignment_task_id=task.id,
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    ))
    await db.commit()


# ---------------------------------------------------------------------------
# AI 出题
# ---------------------------------------------------------------------------

@pytest.fixture
def llm_configured(monkeypatch):
    """给 AI 出题的用例配一个端点。

    不这么做就会依赖开发机上 apps/api/.env 里恰好有没有 LEARNHOUSE_EXT_LLM_*，
    CI 上没有那个文件，用例会在「没配端点」上失败。这里显式设死，
    组织配置那一层由 `test_org_config_overrides_env` 单独覆盖。
    """
    monkeypatch.setenv("LEARNHOUSE_EXT_LLM_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("LEARNHOUSE_EXT_LLM_API_KEY", "test-key")
    monkeypatch.delenv("LEARNHOUSE_EXT_LLM_MODEL", raising=False)

_LLM_REPLY = """```json
{"name": "AI 出的题", "publish": true, "tasks": [
  {"kind": "quiz", "questions": [{"text": "CNC 的 C 指什么？", "options": [
    {"text": "计算机", "correct": true}, {"text": "控制", "correct": false}]}]}
]}
```"""


async def test_draft_forces_draft_and_validates(
    db, org, course, chapter, page_activity, admin_user, mock_request,
    bypass_ext_rbac, llm_configured,
):
    with patch.object(llm_mod, "chat_completion", new=AsyncMock(return_value=_LLM_REPLY)):
        with patch.object(draft_svc.llm_mod, "chat_completion",
                          new=AsyncMock(return_value=_LLM_REPLY)):
            out = await draft_svc.draft_from_activity(
                mock_request, course.course_uuid, page_activity.activity_uuid,
                admin_user, db, n=1, kinds=["quiz"], model="test-model",
            )
    # 模型说 publish=true，这里必须强制改回草稿
    assert out["spec"]["publish"] is False
    assert out["validation"]["task_count"] == 1
    assert out["activity_name"] == "第一节 数控基础"


async def test_draft_reports_extra_kinds(
    db, org, course, chapter, page_activity, admin_user, mock_request,
    bypass_ext_rbac, llm_configured,
):
    reply = (
        '{"name": "x", "tasks": ['
        '{"kind": "quiz", "questions": [{"text": "?", "options": ['
        '{"text": "A", "correct": true}, {"text": "B", "correct": false}]}]},'
        '{"kind": "short_answer", "prompt": "?", "answers": ["a"]}]}'
    )
    with patch.object(draft_svc.llm_mod, "chat_completion",
                      new=AsyncMock(return_value=reply)):
        out = await draft_svc.draft_from_activity(
            mock_request, course.course_uuid, page_activity.activity_uuid,
            admin_user, db, n=2, kinds=["quiz"], model="m",
        )
    assert any("多出了" in w for w in out["validation"]["warnings"])


async def test_draft_normalizes_invented_enum_values(
    db, org, course, chapter, page_activity, admin_user, mock_request,
    bypass_ext_rbac, llm_configured,
):
    """模型真的会自己发明枚举值 —— 线上实测两次都把 grading_type 填成 MIXED。

    这种字段和题目内容无关，不该让整份 spec 报废；改回默认值并在警告里说清原值。
    """
    reply = (
        '{"name": "x", "grading_type": "MIXED", "solution_reveal": "ON_SUBMIT",'
        ' "due_date": "下周三", "tasks": ['
        '{"kind": "quiz", "questions": [{"text": "?", "options": ['
        '{"text": "A", "correct": true}, {"text": "B", "correct": false}]}]}]}'
    )
    with patch.object(draft_svc.llm_mod, "chat_completion",
                      new=AsyncMock(return_value=reply)):
        out = await draft_svc.draft_from_activity(
            mock_request, course.course_uuid, page_activity.activity_uuid,
            admin_user, db, kinds=["quiz"], model="m",
        )
    assert out["spec"]["grading_type"] == "NUMERIC"
    assert out["spec"]["solution_reveal"] == "NEVER"
    assert out["spec"]["due_date"] is None
    fixed = [w for w in out["validation"]["warnings"] if "改回默认值" in w]
    assert len(fixed) == 1
    assert "MIXED" in fixed[0] and "ON_SUBMIT" in fixed[0] and "下周三" in fixed[0]


async def test_draft_retries_once_then_gives_up(
    db, org, course, chapter, page_activity, admin_user, mock_request,
    bypass_ext_rbac, llm_configured,
):
    chat = AsyncMock(return_value="模型今天不想输出 JSON")
    with patch.object(draft_svc.llm_mod, "chat_completion", new=chat):
        with pytest.raises(SpecError) as e:
            await draft_svc.draft_from_activity(
                mock_request, course.course_uuid, page_activity.activity_uuid,
                admin_user, db, model="m",
            )
    assert chat.await_count == 2
    assert "解析不出 JSON" in str(e.value)


async def test_draft_refuses_short_page(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
    llm_configured,
):
    """conftest 的 activity 正文是空的，出不了题。"""
    with pytest.raises(SpecError) as e:
        await draft_svc.draft_from_activity(
            mock_request, course.course_uuid, activity.activity_uuid,
            admin_user, db, model="m",
        )
    assert "太短" in str(e.value)


async def test_draft_rejects_activity_from_another_course(
    db, org, other_org, course, chapter, page_activity, admin_user, mock_request,
    bypass_ext_rbac, llm_configured,
):
    stray = Activity(
        id=77, name="别的课的页", activity_type=ActivityTypeEnum.TYPE_DYNAMIC,
        activity_sub_type=ActivitySubTypeEnum.SUBTYPE_DYNAMIC_PAGE,
        content={}, published=True, org_id=other_org.id, course_id=999,
        activity_uuid="activity_stray",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(stray)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await draft_svc.draft_from_activity(
            mock_request, course.course_uuid, "activity_stray", admin_user, db, model="m",
        )
    assert e.value.status_code == 400


async def test_draft_without_model_is_503(
    db, org, course, chapter, page_activity, admin_user, mock_request, bypass_ext_rbac,
    llm_configured,
):
    """配了端点但没配默认模型，且请求里也没传 —— 该报「没配置」而不是瞎调。"""
    with pytest.raises(llm_mod.LLMNotConfiguredError):
        await draft_svc.draft_from_activity(
            mock_request, course.course_uuid, page_activity.activity_uuid,
            admin_user, db,
        )


async def test_draft_without_endpoint_is_503(
    db, org, course, chapter, page_activity, admin_user, mock_request, bypass_ext_rbac,
    monkeypatch,
):
    monkeypatch.delenv("LEARNHOUSE_EXT_LLM_BASE_URL", raising=False)
    with pytest.raises(llm_mod.LLMNotConfiguredError):
        await draft_svc.draft_from_activity(
            mock_request, course.course_uuid, page_activity.activity_uuid,
            admin_user, db, model="m",
        )


async def test_org_config_overrides_env(db, org, monkeypatch):
    """组织配置的 ext 段要能盖过环境变量 —— 同一台机器上可能跑多个组织。"""
    from datetime import datetime as _dt

    from src.db.organization_config import OrganizationConfig
    from src.services.ext.assign_tools import llm as llm_module

    monkeypatch.setenv("LEARNHOUSE_EXT_LLM_BASE_URL", "https://from-env/v1")
    monkeypatch.setenv("LEARNHOUSE_EXT_LLM_MODEL", "env-model")

    from_env = await llm_module.llm_config(db, org.id)
    assert from_env["base"] == "https://from-env/v1"
    assert from_env["model"] == "env-model"

    db.add(OrganizationConfig(
        org_id=org.id,
        config={"ext": {"llm_base_url": "https://from-org/v1/", "llm_model": "org-model"}},
        creation_date=str(_dt.now()),
        update_date=str(_dt.now()),
    ))
    await db.commit()

    from_org = await llm_module.llm_config(db, org.id)
    assert from_org["base"] == "https://from-org/v1"   # 末尾的斜杠会被去掉
    assert from_org["model"] == "org-model"


# ---------------------------------------------------------------------------
# 按 spec 建作业
# ---------------------------------------------------------------------------

async def test_create_from_spec_builds_activity_assignment_and_tasks(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await create_from_spec(
        mock_request, course.course_uuid, chapter.id, _GOOD_SPEC, admin_user, db,
    )
    assert out["task_count"] == 2
    assert out["published"] is False

    assignment = (await db.execute(
        select(Assignment).where(Assignment.assignment_uuid == out["assignment_uuid"])
    )).scalars().first()
    assert assignment is not None
    assert assignment.course_id == course.id
    assert assignment.published is False

    tasks = (await db.execute(
        select(AssignmentTask).where(AssignmentTask.assignment_id == assignment.id)
    )).scalars().all()
    assert len(tasks) == 2
    assert {t.assignment_type.value for t in tasks} == {"QUIZ", "SHORT_ANSWER"}

    shell = (await db.execute(
        select(Activity).where(Activity.activity_uuid == out["activity_uuid"])
    )).scalars().first()
    assert shell.activity_type == ActivityTypeEnum.TYPE_ASSIGNMENT


async def test_create_from_spec_publish_override(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await create_from_spec(
        mock_request, course.course_uuid, chapter.id, _GOOD_SPEC, admin_user, db,
        publish_override=True,
    )
    assert out["published"] is True


async def test_create_from_spec_rejects_foreign_chapter(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    from src.db.courses.chapters import Chapter

    foreign = Chapter(
        id=99, name="别的课的章", description="", org_id=org.id, course_id=999,
        chapter_uuid="chapter_foreign",
        creation_date=str(datetime.now()), update_date=str(datetime.now()),
    )
    db.add(foreign)
    await db.commit()
    with pytest.raises(HTTPException) as e:
        await create_from_spec(
            mock_request, course.course_uuid, 99, _GOOD_SPEC, admin_user, db,
        )
    assert e.value.status_code == 400


async def test_create_from_spec_bad_spec_creates_nothing(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    before = len((await db.execute(select(Activity))).scalars().all())
    with pytest.raises(SpecError):
        await create_from_spec(
            mock_request, course.course_uuid, chapter.id,
            {"name": "坏的", "tasks": [{"kind": "number_answer", "prompt": "?"}]},
            admin_user, db,
        )
    after = len((await db.execute(select(Activity))).scalars().all())
    assert before == after


# ---------------------------------------------------------------------------
# 随堂测
# ---------------------------------------------------------------------------

async def test_quick_quiz_is_formative_by_default(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await quiz_svc.create_quick_quiz(
        mock_request, course.course_uuid, chapter.id, "第 3 周随堂测",
        [_GOOD_SPEC["tasks"][0]], admin_user, db,
    )
    assignment = (await db.execute(
        select(Assignment).where(Assignment.assignment_uuid == out["assignment_uuid"])
    )).scalars().first()
    assert assignment.ungraded is True
    assert assignment.solution_reveal.value == "ON_SUBMISSION"
    assert assignment.show_correct_answers is True
    # 形成性与自动判分互斥，上游 create_assignment 会把 auto_grading 归零
    assert assignment.auto_grading is False
    assert assignment.published is False


async def test_quick_quiz_graded_mode_never_reveals(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await quiz_svc.create_quick_quiz(
        mock_request, course.course_uuid, chapter.id, "计分小测",
        [_GOOD_SPEC["tasks"][0]], admin_user, db, formative=False,
    )
    assignment = (await db.execute(
        select(Assignment).where(Assignment.assignment_uuid == out["assignment_uuid"])
    )).scalars().first()
    assert assignment.ungraded is False
    assert assignment.solution_reveal.value == "NEVER"


async def test_quick_quiz_needs_questions(
    db, org, course, chapter, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    with pytest.raises(SpecError):
        await quiz_svc.create_quick_quiz(
            mock_request, course.course_uuid, chapter.id, "空的", [], admin_user, db,
        )


async def test_quiz_results_counts_per_question(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    assignment = await _make_assignment(db, org, course, chapter, activity, ungraded=True)
    contents = {
        "questions": [{
            "questionUUID": "q1", "questionText": "CNC 的 C？", "response_type": "single",
            "options": [
                {"optionUUID": "o1", "text": "计算机", "assigned_right_answer": True},
                {"optionUUID": "o2", "text": "控制", "assigned_right_answer": False},
            ],
        }],
        "grading_mode": "all_or_nothing",
    }
    task = await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=200, atype=AssignmentTaskTypeEnum.QUIZ, contents=contents, title="单选",
    )
    await _make_student(db, 11, "张三")
    await _make_student(db, 12, "李四")
    # 张三对，李四错
    await _submit(db, assignment, task, 11, {"submissions": [
        {"questionUUID": "q1", "optionUUID": "o1", "answer": True},
        {"questionUUID": "q1", "optionUUID": "o2", "answer": False},
    ]}, sid=1)
    await _submit(db, assignment, task, 12, {"submissions": [
        {"questionUUID": "q1", "optionUUID": "o1", "answer": False},
        {"questionUUID": "q1", "optionUUID": "o2", "answer": True},
    ]}, sid=2)

    out = await quiz_svc.quiz_results(
        mock_request, assignment.assignment_uuid, admin_user, db,
    )
    assert out["formative"] is True
    assert out["roster_count"] == 2
    assert out["submitted_count"] == 2
    q = out["per_question"][0]
    assert (q["right"], q["wrong"], q["correct_rate"]) == (1, 1, 50.0)
    names = {s["name"]: s["score_percent"] for s in out["students"]}
    assert names == {"张三": 100.0, "李四": 0.0}


async def test_quiz_results_marks_file_task_manual(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    assignment = await _make_assignment(db, org, course, chapter, activity, aid=101)
    await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=201, atype=AssignmentTaskTypeEnum.FILE_SUBMISSION, contents={}, title="交报告",
    )
    out = await quiz_svc.quiz_results(
        mock_request, assignment.assignment_uuid, admin_user, db,
    )
    assert out["per_question"][0]["manual_only"] is True
    assert out["per_question"][0]["correct_rate"] is None


async def test_quiz_results_404(db, org, course, admin_user, mock_request, bypass_ext_rbac):
    with pytest.raises(HTTPException) as e:
        await quiz_svc.quiz_results(mock_request, "assignment_nope", admin_user, db)
    assert e.value.status_code == 404


# ---------------------------------------------------------------------------
# 查重
# ---------------------------------------------------------------------------

async def test_similarity_scoring_basics():
    assert sim_svc.similarity(sim_svc.normalize("计算机数控"), sim_svc.normalize("计算机数控")) == 1.0
    # 归一化把标点和空格吃掉，这两串应该被当成同一个答案
    a = sim_svc.normalize("计算机 数控（CNC）")
    b = sim_svc.normalize("计算机数控cnc")
    assert a == b
    assert sim_svc.similarity("完全不同的一串", "另外一串东西") < 0.8


async def test_similarity_finds_near_identical_pair(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    assignment = await _make_assignment(db, org, course, chapter, activity, aid=102)
    task = await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=202, atype=AssignmentTaskTypeEnum.SHORT_ANSWER,
        contents={"prompt": "简述数控机床的组成", "correct_answers": ["控制系统"],
                  "match_mode": "contains"},
        title="简答",
    )
    long_a = "数控机床主要由控制系统伺服驱动系统和机械本体三大部分组成其中控制系统负责解释加工程序"
    long_b = "数控机床主要由控制系统伺服驱动系统和机械本体三大部分构成其中控制系统负责解释加工程序"
    long_c = "增材制造是一种逐层堆积材料的成形工艺与传统的减材加工在原理上完全不同应用场景也不一样"
    for uid, text, sid in ((21, long_a, 11), (22, long_b, 12), (23, long_c, 13)):
        await _make_student(db, uid, f"学生{uid}")
        await _submit(db, assignment, task, uid, {"answer": text}, sid=sid)

    out = await sim_svc.check_assignment(
        mock_request, assignment.assignment_uuid, admin_user, db, threshold=0.8,
    )
    assert len(out["pairs"]) == 1
    pair = out["pairs"][0]
    assert {pair["user_a_id"], pair["user_b_id"]} == {21, 22}
    assert pair["similarity"] >= 0.8
    assert pair["snippet"]
    assert out["disclaimer"]


async def test_similarity_skips_objective_and_short_answers(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    assignment = await _make_assignment(db, org, course, chapter, activity, aid=103)
    await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=203, atype=AssignmentTaskTypeEnum.QUIZ, contents={"questions": []}, title="选择",
    )
    short_task = await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=204, atype=AssignmentTaskTypeEnum.SHORT_ANSWER,
        contents={"prompt": "?", "correct_answers": ["对"], "match_mode": "contains"},
        title="太短",
    )
    for uid, sid in ((31, 21), (32, 22)):
        await _make_student(db, uid, f"学生{uid}")
        await _submit(db, assignment, short_task, uid, {"answer": "好"}, sid=sid)

    out = await sim_svc.check_assignment(
        mock_request, assignment.assignment_uuid, admin_user, db,
    )
    assert out["pairs"] == []
    assert any("跳过客观题" in n for n in out["notes"])
    assert any("太短" in s["reason"] for s in out["skipped"])


async def test_similarity_excludes_matching_correct_answers(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    """两个人都写对了标准答案，不该被当成互抄。"""
    right = "数控机床由控制系统伺服驱动系统和机械本体三大部分组成这是标准答案"
    assignment = await _make_assignment(db, org, course, chapter, activity, aid=104)
    task = await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=205, atype=AssignmentTaskTypeEnum.SHORT_ANSWER,
        contents={"prompt": "?", "correct_answers": [right], "match_mode": "contains"},
        title="简答",
    )
    for uid, sid in ((41, 31), (42, 32)):
        await _make_student(db, uid, f"学生{uid}")
        await _submit(db, assignment, task, uid, {"answer": right}, sid=sid)

    out = await sim_svc.check_assignment(
        mock_request, assignment.assignment_uuid, admin_user, db,
    )
    assert out["pairs"] == []
    assert all("标准答案" in s["reason"] for s in out["skipped"])


async def test_similarity_reports_identical_files(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    assignment = await _make_assignment(db, org, course, chapter, activity, aid=105)
    task = await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=206, atype=AssignmentTaskTypeEnum.FILE_SUBMISSION, contents={}, title="交报告",
    )
    for uid, sid in ((51, 41), (52, 42)):
        await _make_student(db, uid, f"学生{uid}")
        await _submit(db, assignment, task, uid, {"fileUUID": f"report_{uid}.bin"}, sid=sid)

    with patch.object(sim_svc, "read_file_content", return_value=b"\x00same bytes"):
        out = await sim_svc.check_assignment(
            mock_request, assignment.assignment_uuid, admin_user, db,
        )
    assert len(out["identical_files"]) == 1
    assert out["identical_files"][0]["users"] == ["学生51", "学生52"]
    assert out["pairs"][0]["same_file"] is True


async def test_extract_file_text_plaintext_and_unknown():
    text, how = sim_svc.extract_file_text("a.txt", "你好世界".encode("utf-8"))
    assert (text, how) == ("你好世界", "plaintext")
    assert sim_svc.extract_file_text("a.docx", b"\x00\x01") == ("", "none")


# ---------------------------------------------------------------------------
# 学期复用
# ---------------------------------------------------------------------------

async def test_clone_term_dry_run_writes_nothing(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    await _make_assignment(
        db, org, course, chapter, activity, due_date="2026-03-01", aid=110,
    )
    from src.db.courses.courses import Course

    before = len((await db.execute(select(Course))).scalars().all())
    out = await clone_svc.clone_term(
        mock_request, course.course_uuid, admin_user, db,
        name="2026 春", shift_days=180, confirm=False,
    )
    after = len((await db.execute(select(Course))).scalars().all())
    assert out["confirmed"] is False
    assert before == after
    assert out["assignment_count"] == 1
    assert out["assignments"][0]["new_due_date"] == "2026-08-28"


async def test_clone_term_rejects_conflicting_args(
    db, org, course, admin_user, mock_request, bypass_ext_rbac,
):
    with pytest.raises(SpecError):
        await clone_svc.clone_term(
            mock_request, course.course_uuid, admin_user, db,
            shift_days=7, due_date="2026-01-01",
        )


async def test_clone_term_copies_assignments_and_tasks(
    db, org, course, chapter, activity, admin_user, mock_request,
    bypass_ext_rbac, bypass_usage,
):
    assignment = await _make_assignment(
        db, org, course, chapter, activity, due_date="2026-03-01", aid=111,
    )
    await _make_task(
        db, org, course, chapter, activity, assignment,
        tid=210, atype=AssignmentTaskTypeEnum.SHORT_ANSWER,
        contents={"prompt": "?", "correct_answers": ["a"], "match_mode": "contains"},
    )

    async def _fake_clone(request, course_uuid, current_user, db_session):
        """只复制这次测试关心的部分：课程 + 章节 + 活动（保序）。"""
        from src.db.courses.chapters import Chapter
        from src.db.courses.course_chapters import CourseChapter
        from src.db.courses.courses import Course as C

        new_course = C(
            name=f"{course.name} (Copy)", description="", public=False, published=True,
            open_to_contributors=False, org_id=org.id, course_uuid="course_cloned",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        )
        db_session.add(new_course)
        await db_session.flush()
        new_chapter = Chapter(
            name=chapter.name, description="", org_id=org.id, course_id=new_course.id,
            chapter_uuid="chapter_cloned",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        )
        db_session.add(new_chapter)
        await db_session.flush()
        db_session.add(CourseChapter(
            chapter_id=new_chapter.id, course_id=new_course.id, org_id=org.id, order=1,
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        ))
        new_activity = Activity(
            name=activity.name, activity_type=activity.activity_type,
            activity_sub_type=activity.activity_sub_type, content={}, published=True,
            org_id=org.id, course_id=new_course.id, activity_uuid="activity_cloned",
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        )
        db_session.add(new_activity)
        await db_session.flush()
        db_session.add(ChapterActivity(
            order=1, chapter_id=new_chapter.id, activity_id=new_activity.id,
            course_id=new_course.id, org_id=org.id,
            creation_date=str(datetime.now()), update_date=str(datetime.now()),
        ))
        await db_session.commit()
        return new_course

    with patch.object(clone_svc, "clone_course", new=_fake_clone):
        out = await clone_svc.clone_term(
            mock_request, course.course_uuid, admin_user, db,
            name="2026 春 数控技术", shift_days=180, unpublish=True, confirm=True,
        )

    assert out["confirmed"] is True
    assert out["copied_count"] == 1
    assert out["copied"][0]["new_due_date"] == "2026-08-28"
    assert out["copied"][0]["task_count"] == 1

    new_assignment = (await db.execute(
        select(Assignment).where(
            Assignment.assignment_uuid == out["copied"][0]["assignment_uuid"]
        )
    )).scalars().first()
    assert new_assignment.published is False
    assert new_assignment.due_date == "2026-08-28"
    new_tasks = (await db.execute(
        select(AssignmentTask).where(AssignmentTask.assignment_id == new_assignment.id)
    )).scalars().all()
    assert len(new_tasks) == 1
    # 题目内容原样带过来
    assert new_tasks[0].contents["correct_answers"] == ["a"]
    # 学生的提交不复制
    assert (await db.execute(
        select(AssignmentUserSubmission).where(
            AssignmentUserSubmission.assignment_id == new_assignment.id
        )
    )).scalars().all() == []


async def test_shift_due_dry_run_and_apply(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    a1 = await _make_assignment(
        db, org, course, chapter, activity, title="有截止", due_date="2026-03-01", aid=120,
    )
    await _make_assignment(
        db, org, course, chapter, activity, title="没截止", due_date=None, aid=121,
    )

    dry = await clone_svc.shift_due(
        mock_request, course.course_uuid, admin_user, db, days=7, confirm=False,
    )
    assert dry["confirmed"] is False
    assert dry["changed_count"] == 1
    assert dry["changed"][0]["new_due_date"] == "2026-03-08"
    assert dry["skipped"][0]["reason"] == "没有设过截止日期"
    await db.refresh(a1)
    assert a1.due_date == "2026-03-01"   # 试算不改数据

    real = await clone_svc.shift_due(
        mock_request, course.course_uuid, admin_user, db, days=7, confirm=True,
    )
    assert real["confirmed"] is True
    await db.refresh(a1)
    assert a1.due_date == "2026-03-08"


async def test_shift_due_only_future_skips_past(
    db, org, course, chapter, activity, admin_user, mock_request, bypass_ext_rbac,
):
    await _make_assignment(
        db, org, course, chapter, activity, due_date="2020-01-01", aid=122,
    )
    out = await clone_svc.shift_due(
        mock_request, course.course_uuid, admin_user, db,
        days=7, only_future=True, confirm=False,
    )
    assert out["changed_count"] == 0
    assert "已过期" in out["skipped"][0]["reason"]


async def test_shift_due_requires_exactly_one_mode(
    db, org, course, admin_user, mock_request, bypass_ext_rbac,
):
    with pytest.raises(SpecError):
        await clone_svc.shift_due(mock_request, course.course_uuid, admin_user, db)
    with pytest.raises(SpecError):
        await clone_svc.shift_due(
            mock_request, course.course_uuid, admin_user, db,
            days=1, due_date="2026-01-01",
        )


async def test_shift_date_helper():
    assert clone_svc.shift_date("2026-03-01", 180) == "2026-08-28"
    assert clone_svc.shift_date("2026-03-01T23:59:00", 1) == "2026-03-02T23:59:00"
    assert clone_svc.shift_date("下周三", 1) is None
    assert clone_svc.shift_date(None, 1) is None


# ---------------------------------------------------------------------------
# 版本回滚
# ---------------------------------------------------------------------------

@pytest.fixture
async def versioned_page(db, org, page_activity):
    from src.db.courses.activity_versions import ActivityVersion

    for n, text in ((1, "第一稿：数控机床由三部分组成。"), (2, "第二稿：数控机床由控制系统等三部分组成。")):
        db.add(ActivityVersion(
            activity_id=page_activity.id, org_id=org.id, version_number=n,
            content={"type": "doc", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]},
            ]},
            created_by_id=None, created_at=datetime.now(),
        ))
    await db.commit()
    return page_activity


async def test_list_versions(
    db, org, course, versioned_page, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await ver_svc.list_versions(
        mock_request, versioned_page.activity_uuid, admin_user, db,
    )
    assert out["current_version"] == 3
    assert [v["version_number"] for v in out["versions"]] == [2, 1]
    assert all(v["chars"] > 0 for v in out["versions"])


async def test_version_markdown(
    db, org, course, versioned_page, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await ver_svc.version_markdown(
        mock_request, versioned_page.activity_uuid, 1, admin_user, db,
    )
    assert "第一稿" in out["markdown"]
    assert out["label"] == "v1"


async def test_diff_between_two_versions(
    db, org, course, versioned_page, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await ver_svc.diff_versions(
        mock_request, versioned_page.activity_uuid, 1, 2, admin_user, db,
    )
    assert out["identical"] is False
    assert out["added_lines"] == 1
    assert out["removed_lines"] == 1
    assert "第二稿" in out["diff"]
    assert out["label_a"] == "v1" and out["label_b"] == "v2"


async def test_diff_against_current_uses_none(
    db, org, course, versioned_page, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await ver_svc.diff_versions(
        mock_request, versioned_page.activity_uuid, 2, None, admin_user, db,
    )
    assert out["label_b"] == "当前（v3）"
    assert "CNC" in out["markdown_b"]


async def test_restore_dry_run_writes_nothing(
    db, org, course, versioned_page, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    out = await ver_svc.restore(
        mock_request, versioned_page.activity_uuid, 1, admin_user, db, confirm=False,
    )
    assert out["confirmed"] is False
    assert out["restore_to"] == 1
    assert out["diff"]
    await db.refresh(versioned_page)
    assert versioned_page.current_version == 3
    assert "CNC" in tiptap_to_markdown(versioned_page.content)


async def test_restore_backs_up_current_first(
    db, org, course, versioned_page, admin_user, mock_request, bypass_ext_rbac, bypass_usage,
):
    from src.db.courses.activity_versions import ActivityVersion

    out = await ver_svc.restore(
        mock_request, versioned_page.activity_uuid, 1, admin_user, db, confirm=True,
    )
    assert out["confirmed"] is True
    assert out["current_version"] == 4

    await db.refresh(versioned_page)
    assert "第一稿" in tiptap_to_markdown(versioned_page.content)

    # 回滚前的那一稿被存成了 v3，没有丢
    backup = (await db.execute(
        select(ActivityVersion).where(
            ActivityVersion.activity_id == versioned_page.id,
            ActivityVersion.version_number == 3,
        )
    )).scalars().first()
    assert backup is not None
    assert "CNC" in tiptap_to_markdown(backup.content)


async def test_versions_404(db, org, course, admin_user, mock_request, bypass_ext_rbac):
    with pytest.raises(HTTPException) as e:
        await ver_svc.list_versions(mock_request, "activity_nope", admin_user, db)
    assert e.value.status_code == 404
