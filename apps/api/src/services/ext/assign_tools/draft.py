"""AI 出题：读一个内容页的正文，调大模型生成一份已通过校验的 spec。

移植自 skill/learnhouse/aiquiz.py 的 `draft_from_page`。**只读**：这里不会在
平台上创建任何东西，返回的 spec 一律 `publish=False`，要真的布置得走
`from-spec` 接口。
"""

import re

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.courses import Course
from src.db.users import PublicUser
from src.security.rbac import AccessAction, check_resource_access

from . import llm as llm_mod
from .spec import (
    GRADING_TYPES,
    KIND_LABELS,
    SOLUTION_REVEALS,
    SpecError,
    normalize_kinds,
    validate_spec,
)
from .tiptap import tiptap_to_plain_text

MAX_PAGE_CHARS = 12000
MIN_PAGE_CHARS = 40

PROMPT = """你是一位大学工科课程的命题老师。下面是课程某一节的正文内容。

请根据这段内容出 {n} 道题，题型只能用这些：{kinds}。
要求：
1. 题目必须能从正文里找到依据，不要考正文没讲过的东西；
2. 难度分布：基础概念题为主，可以有一两道计算或应用题；
3. 用中文出题；
4. 选择题每题 4 个选项，选项写成 {{"text": "...", "correct": true/false}} 的字典形式，
   正好标一个 correct 为 true（要多选就标两个及以上）；
5. 简答题的 answers 给 2-3 个等价说法，match_mode 用 "contains"；
6. 数值题必须给 tolerance。

**只输出一个 JSON 对象，不要任何解释文字，不要 markdown 代码围栏。** 结构如下：

{schema}

正文内容：
----
{page}
----
"""

SCHEMA = """{
  "name": "作业标题",
  "description": "一句话说明",
  "publish": false,
  "grading_type": "NUMERIC",
  "tasks": [
    {"kind": "quiz", "title": "选择题", "questions": [
      {"text": "题干", "options": [
        {"text": "选项A", "correct": false},
        {"text": "选项B", "correct": true},
        {"text": "选项C", "correct": false},
        {"text": "选项D", "correct": false}]}]},
    {"kind": "short_answer", "title": "简答题", "prompt": "题干",
     "answers": ["答案一", "答案二"], "match_mode": "contains", "explanation": "解析"},
    {"kind": "number_answer", "title": "数值题", "prompt": "题干",
     "value": 12.5, "tolerance": 0.1, "unit": "mm"}
  ]
}"""


async def draft_from_activity(
    request: Request,
    course_uuid: str,
    activity_uuid: str,
    current_user: PublicUser,
    db_session: AsyncSession,
    n: int = 5,
    kinds: list[str] | None = None,
    model: str | None = None,
    name: str | None = None,
) -> dict:
    """读内容页正文 → 调大模型 → 校验 → 返回 spec（不落库）。"""
    course = (await db_session.execute(
        select(Course).where(Course.course_uuid == course_uuid)
    )).scalars().first()
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")

    await check_resource_access(
        request, db_session, current_user, course.course_uuid, AccessAction.UPDATE
    )

    activity = (await db_session.execute(
        select(Activity).where(Activity.activity_uuid == activity_uuid)
    )).scalars().first()
    if not activity:
        raise HTTPException(status_code=404, detail="内容页不存在")
    if activity.course_id != course.id:
        raise HTTPException(status_code=400, detail="这个内容页不属于该课程")

    body = tiptap_to_plain_text(activity.content or {})
    if len(body) < MIN_PAGE_CHARS:
        raise SpecError(
            "这一页的正文太短（%d 字），出不出有意义的题。"
            "确认《%s》是一个富文本内容页，而不是视频或 PDF 活动。"
            % (len(body), activity.name)
        )
    body = body[:MAX_PAGE_CHARS]

    kinds = normalize_kinds(kinds or ["quiz", "short_answer"])
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise SpecError("题量必须是整数")
    n = max(1, min(20, n))

    cfg = llm_mod.require_configured(await llm_mod.llm_config(db_session, course.org_id))
    model = (model or cfg["model"] or "").strip()
    if not model:
        raise llm_mod.LLMNotConfiguredError(
            "没有指定模型。请在请求里传 model，或在组织设置的 ext 段填 llm_model / "
            "设置环境变量 LEARNHOUSE_EXT_LLM_MODEL。"
        )

    prompt = PROMPT.format(
        n=n,
        kinds="、".join(KIND_LABELS.get(k, k) + "(" + k + ")" for k in kinds),
        schema=SCHEMA,
        page=body,
    )
    messages = [
        {"role": "system", "content": "你只输出 JSON，不输出任何其它文字。"},
        {"role": "user", "content": prompt},
    ]

    spec = None
    attempts = 0
    last_err = None
    while attempts < 2 and spec is None:
        attempts += 1
        raw = await llm_mod.chat_completion(cfg, model, messages)
        try:
            spec = llm_mod.extract_json(raw)
        except (ValueError, TypeError) as e:
            last_err = str(e)
            messages = messages + [
                {"role": "assistant", "content": (raw or "")[:2000]},
                {
                    "role": "user",
                    "content": "上一次的输出解析失败（%s）。"
                               "请重新只输出那个 JSON 对象，不要围栏、不要解释。" % e,
                },
            ]
    if spec is None:
        raise SpecError(
            "模型连续两次输出都解析不出 JSON（%s）。换一个模型再试，"
            "或者直接按模板自己写 spec。" % last_err
        )
    if not isinstance(spec, dict):
        raise SpecError("模型返回的不是一个 JSON 对象")

    spec.setdefault("name", name or ("%s 随堂练习" % (activity.name or "本节")))
    if name:
        spec["name"] = name
    # AI 出的题一律先草稿，等老师过目
    spec["publish"] = False
    spec.setdefault(
        "description",
        "由大模型根据《%s》正文自动生成，请老师核对后再发布。" % (activity.name or ""),
    )

    # 模型偶尔会自己发明枚举值（实测见过 grading_type: "MIXED"）。这些字段对题目
    # 内容毫无影响，为它整份 spec 报废不划算 —— 改回默认值并告诉老师。
    fixed_fields = []
    if spec.get("grading_type") not in GRADING_TYPES:
        if "grading_type" in spec:
            fixed_fields.append("grading_type（原值 %s）" % spec["grading_type"])
        spec["grading_type"] = "NUMERIC"
    if spec.get("solution_reveal") is not None and spec["solution_reveal"] not in SOLUTION_REVEALS:
        fixed_fields.append("solution_reveal（原值 %s）" % spec["solution_reveal"])
        spec["solution_reveal"] = "NEVER"
    if spec.get("due_date") is not None and not re.match(r"^\d{4}-\d{2}-\d{2}$", str(spec["due_date"])):
        fixed_fields.append("due_date（原值 %s）" % spec["due_date"])
        spec["due_date"] = None

    check = validate_spec(spec)
    if fixed_fields:
        check["warnings"] = list(check["warnings"]) + [
            "模型给的这些字段不是合法取值，已经改回默认值：" + "、".join(fixed_fields)
        ]
    # 提示词里的题型是软约束，模型偶尔会多出一种题型。不删它（内容可能是好的），
    # 但要说出来，让老师知道拿到的东西和他点的不一样。
    extra_kinds = sorted({t["kind"] for t in check["tasks"]} - set(kinds))
    if extra_kinds:
        check["warnings"] = list(check["warnings"]) + [
            "你要的是 %s，模型还多出了 %s。不需要就把对应的题删掉。"
            % (
                "、".join(KIND_LABELS.get(k, k) for k in kinds),
                "、".join(KIND_LABELS.get(k, k) for k in extra_kinds),
            )
        ]

    return {
        "activity_uuid": activity.activity_uuid,
        "activity_name": activity.name,
        "course_uuid": course.course_uuid,
        "model": model,
        "endpoint": cfg["base"],
        "attempts": attempts,
        "page_chars": len(body),
        "spec": spec,
        "validation": {
            k: check[k]
            for k in ("ok", "task_count", "total_max_grade", "summary", "warnings")
        },
    }
