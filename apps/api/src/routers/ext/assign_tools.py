"""教学工具 · 作业工具的 HTTP 接口（SYSU-SAM 扩展）。

路由层只做签名、文档和错误翻译，业务逻辑全在
`src/services/ext/assign_tools/` 里。所有路径带 `/ext/` 前缀，一眼能看出
不是上游的接口。

权限：骨架的 `deps.require_teacher` 做组织级第一道门（Admin / Maintainer /
Instructor），**因此每个接口都要带 `?org_id=<id>`**；课程级权限再由每个 service
自己调 `check_resource_access` 收窄。
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.users import PublicUser
from src.services.ext.assign_tools import clone as clone_svc
from src.services.ext.assign_tools import draft as draft_svc
from src.services.ext.assign_tools import quickquiz as quiz_svc
from src.services.ext.assign_tools import similarity as sim_svc
from src.services.ext.assign_tools import versions as ver_svc
from src.routers.ext.deps import require_teacher
from src.services.ext.assign_tools.create import create_from_spec
from src.services.ext.assign_tools.llm import (
    LLMNotConfiguredError,
    list_models,
    llm_config,
)
from src.services.ext.assign_tools.spec import SpecError, spec_template, validate_spec

router = APIRouter()


def _translate(e: SpecError) -> HTTPException:
    """spec / LLM 层的错误统一翻成 HTTP 错误：没配端点是 503，其余是 400。"""
    if isinstance(e, LLMNotConfiguredError):
        return HTTPException(status_code=503, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------- 请求体


class SpecBody(BaseModel):
    spec: dict


class DraftBody(BaseModel):
    n: int = Field(default=5, ge=1, le=20)
    types: list[str] = Field(default_factory=lambda: ["quiz", "short_answer"])
    model: Optional[str] = None
    name: Optional[str] = None


class FromSpecBody(BaseModel):
    spec: dict
    publish: bool = False


class QuickQuizBody(BaseModel):
    title: str
    questions: list[dict]
    formative: bool = True
    publish: bool = False
    due_date: Optional[str] = None
    description: str = ""


class CloneTermBody(BaseModel):
    name: Optional[str] = None
    shift_days: Optional[int] = None
    due_date: Optional[str] = None
    unpublish: bool = True
    confirm: bool = False


class ShiftDueBody(BaseModel):
    days: Optional[int] = None
    due_date: Optional[str] = None
    only_future: bool = False
    confirm: bool = False


class RestoreBody(BaseModel):
    version: int
    confirm: bool = False


# ---------------------------------------------------------------- spec 校验与模板


@router.post(
    "/spec/validate",
    tags=["ext"],
    summary="校验一份作业 spec",
    description="纯本地校验，不联网也不写任何东西。返回每道题的预览与警告。",
    responses={
        200: {"description": "校验通过，返回预览"},
        400: {"description": "spec 有问题，detail 里是中文说明"},
        401: {"description": "需要登录"},
    },
)
async def api_validate_spec(
    *,
    body: SpecBody,
    current_user: PublicUser = Depends(require_teacher),
) -> Any:
    try:
        return validate_spec(body.spec)
    except SpecError as e:
        raise _translate(e)


@router.get(
    "/spec/template",
    tags=["ext"],
    summary="取一份 spec 模板",
    description="按题型返回带注释的 spec 模板，以 _ 开头的键是注释，校验时会忽略。",
    responses={
        200: {"description": "模板"},
        400: {"description": "题型名不对"},
        401: {"description": "需要登录"},
    },
)
async def api_spec_template(
    *,
    types: Optional[str] = Query(default=None, description="逗号分隔的题型，如 quiz,short_answer"),
    current_user: PublicUser = Depends(require_teacher),
) -> Any:
    kinds = [k for k in (types or "").split(",") if k.strip()] or None
    try:
        return spec_template(kinds)
    except SpecError as e:
        raise _translate(e)


@router.get(
    "/llm/models",
    tags=["ext"],
    summary="列出可用的大模型",
    description="读环境变量里配置的 OpenAI 兼容端点，列出它支持的模型 id。",
    responses={
        200: {"description": "模型列表"},
        401: {"description": "需要登录"},
        503: {"description": "没有配置大模型端点"},
    },
)
async def api_list_models(
    *,
    org_id: int,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    try:
        return await list_models(await llm_config(db_session, org_id))
    except SpecError as e:
        raise _translate(e)


# ---------------------------------------------------------------- AI 出题


@router.post(
    "/courses/{course_uuid}/activities/{activity_uuid}/draft",
    tags=["ext"],
    summary="读一个内容页，用大模型出题",
    description="只读：读该内容页正文调 LLM 生成 spec 并校验后返回，不在平台上创建任何东西。"
                "返回的 spec 一律是草稿（publish=false）。",
    responses={
        200: {"description": "生成并校验通过的 spec"},
        400: {"description": "正文太短、题型不对，或模型输出解析不出来"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "课程或内容页不存在"},
        503: {"description": "没有配置大模型端点"},
    },
)
async def api_draft_from_activity(
    *,
    request: Request,
    course_uuid: str,
    activity_uuid: str,
    body: DraftBody,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    try:
        return await draft_svc.draft_from_activity(
            request, course_uuid, activity_uuid, current_user, db_session,
            n=body.n, kinds=body.types, model=body.model, name=body.name,
        )
    except SpecError as e:
        raise _translate(e)


@router.post(
    "/courses/{course_uuid}/chapters/{chapter_id}/from-spec",
    tags=["ext"],
    summary="按 spec 建一份作业",
    description="三步建作业：作业壳活动 + assignment 记录 + 每道题。校验在建任何东西之前完成。",
    responses={
        200: {"description": "建好了，返回各 uuid"},
        400: {"description": "spec 有问题，或章节不属于该课程"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "课程或章节不存在"},
    },
)
async def api_create_from_spec(
    *,
    request: Request,
    course_uuid: str,
    chapter_id: int,
    body: FromSpecBody,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    try:
        return await create_from_spec(
            request, course_uuid, chapter_id, body.spec, current_user, db_session,
            publish_override=body.publish,
        )
    except SpecError as e:
        raise _translate(e)


# ---------------------------------------------------------------- 随堂测


@router.post(
    "/courses/{course_uuid}/chapters/{chapter_id}/quick-quiz",
    tags=["ext"],
    summary="建一份随堂测",
    description="默认形成性（不计成绩）且交卷即公布答案。formative=false 会切回计分作业。",
    responses={
        200: {"description": "建好了"},
        400: {"description": "题目有问题，或章节不属于该课程"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "课程或章节不存在"},
    },
)
async def api_quick_quiz(
    *,
    request: Request,
    course_uuid: str,
    chapter_id: int,
    body: QuickQuizBody,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    try:
        return await quiz_svc.create_quick_quiz(
            request, course_uuid, chapter_id, body.title, body.questions,
            current_user, db_session,
            formative=body.formative, publish=body.publish,
            due_date=body.due_date, description=body.description,
        )
    except SpecError as e:
        raise _translate(e)


@router.get(
    "/assignments/{assignment_uuid}/results",
    tags=["ext"],
    summary="随堂测结果：每题答对率与名单",
    description="答对率按题目答案和学生提交本地计算，不依赖服务端判分 —— 形成性作业本来就不判分。"
                "文件题和代码题标为需人工，不进答对率统计。",
    responses={
        200: {"description": "结果"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "作业不存在"},
    },
)
async def api_quiz_results(
    *,
    request: Request,
    assignment_uuid: str,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await quiz_svc.quiz_results(request, assignment_uuid, current_user, db_session)


# ---------------------------------------------------------------- 查重


@router.get(
    "/assignments/{assignment_uuid}/similarity",
    tags=["ext"],
    summary="作业查重",
    description="同一道题内两两比对：文本题用字符 n-gram Jaccard 与 difflib 取大值，"
                "文件题先比 sha256、PDF 再抽文本比。客观题跳过。"
                "结果里的 disclaimer 字段必须原样展示给老师。",
    responses={
        200: {"description": "相似对列表"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "作业不存在"},
    },
)
async def api_similarity(
    *,
    request: Request,
    assignment_uuid: str,
    threshold: float = Query(default=sim_svc.DEFAULT_THRESHOLD, ge=0.1, le=1.0),
    min_length: int = Query(default=sim_svc.MIN_LENGTH, ge=1, le=500),
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await sim_svc.check_assignment(
        request, assignment_uuid, current_user, db_session,
        threshold=threshold, min_length=min_length,
    )


# ---------------------------------------------------------------- 学期复用


@router.post(
    "/courses/{course_uuid}/clone-term",
    tags=["ext"],
    summary="学期复用：克隆课程并复制作业",
    description="confirm=false 只返回将要发生什么的摘要，不写任何东西；confirm=true 才真的执行。"
                "克隆不会复制学生的提交与成绩。",
    responses={
        200: {"description": "摘要（confirm=false）或执行结果（confirm=true）"},
        400: {"description": "参数冲突或日期格式不对"},
        401: {"description": "需要登录"},
        403: {"description": "没有权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_clone_term(
    *,
    request: Request,
    course_uuid: str,
    body: CloneTermBody,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    try:
        return await clone_svc.clone_term(
            request, course_uuid, current_user, db_session,
            name=body.name, shift_days=body.shift_days, due_date=body.due_date,
            unpublish=body.unpublish, confirm=body.confirm,
        )
    except SpecError as e:
        raise _translate(e)


@router.post(
    "/courses/{course_uuid}/shift-due",
    tags=["ext"],
    summary="批量顺延作业截止日期",
    description="顺延天数与统一截止日期二选一。没设过截止日期的作业一律跳过。"
                "confirm=false 只算不改。",
    responses={
        200: {"description": "试算结果（confirm=false）或执行结果（confirm=true）"},
        400: {"description": "参数冲突或日期格式不对"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_shift_due(
    *,
    request: Request,
    course_uuid: str,
    body: ShiftDueBody,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    try:
        return await clone_svc.shift_due(
            request, course_uuid, current_user, db_session,
            days=body.days, due_date=body.due_date,
            only_future=body.only_future, confirm=body.confirm,
        )
    except SpecError as e:
        raise _translate(e)


# ---------------------------------------------------------------- 版本回滚


@router.get(
    "/activities/{activity_uuid}/versions",
    tags=["ext"],
    summary="内容页版本列表",
    responses={
        200: {"description": "版本列表与当前版本号"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的访问权限"},
        404: {"description": "内容页不存在"},
    },
)
async def api_list_versions(
    *,
    request: Request,
    activity_uuid: str,
    limit: int = Query(default=20, ge=1, le=50),
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await ver_svc.list_versions(
        request, activity_uuid, current_user, db_session, limit=limit
    )


@router.get(
    "/activities/{activity_uuid}/versions/{version_number}/markdown",
    tags=["ext"],
    summary="某个版本的 Markdown 全文",
    responses={
        200: {"description": "Markdown 文本"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的访问权限"},
        404: {"description": "内容页或版本不存在"},
    },
)
async def api_version_markdown(
    *,
    request: Request,
    activity_uuid: str,
    version_number: int,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await ver_svc.version_markdown(
        request, activity_uuid, version_number, current_user, db_session
    )


@router.get(
    "/activities/{activity_uuid}/diff",
    tags=["ext"],
    summary="两个版本之间的 unified diff",
    description="a、b 是版本号，任一侧留空表示「当前内容」。diff 做在 Markdown 文本行上。",
    responses={
        200: {"description": "两侧全文与 unified diff 文本"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的访问权限"},
        404: {"description": "内容页或版本不存在"},
    },
)
async def api_diff_versions(
    *,
    request: Request,
    activity_uuid: str,
    a: Optional[int] = Query(default=None, description="左侧版本号，留空表示当前内容"),
    b: Optional[int] = Query(default=None, description="右侧版本号，留空表示当前内容"),
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await ver_svc.diff_versions(
        request, activity_uuid, a, b, current_user, db_session
    )


@router.post(
    "/activities/{activity_uuid}/restore",
    tags=["ext"],
    summary="把内容页回滚到某个版本",
    description="confirm=false 只返回会发生什么的摘要与 diff。回滚前会先把当前内容存成新版本。",
    responses={
        200: {"description": "摘要（confirm=false）或回滚结果（confirm=true）"},
        401: {"description": "需要登录"},
        403: {"description": "没有这门课的编辑权限"},
        404: {"description": "内容页或版本不存在"},
    },
)
async def api_restore_version(
    *,
    request: Request,
    activity_uuid: str,
    body: RestoreBody,
    current_user: PublicUser = Depends(require_teacher),
    db_session: AsyncSession = Depends(get_db_session),
) -> Any:
    return await ver_svc.restore(
        request, activity_uuid, body.version, current_user, db_session,
        confirm=body.confirm,
    )
