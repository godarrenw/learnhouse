# -*- coding: utf-8 -*-
"""SYSU-SAM 内容工具：Markdown 导入导出、视频嵌入解析、虚拟助教、二维码。

挂载点在 `src/routers/ext/__init__.py`（骨架代理维护），前缀 `/ext/content`，
**教师身份这道闸是在挂载时统一加的**（`dependencies=[Depends(require_teacher)]`），
所以本文件里的路由不再各自判断角色。课程级权限另算：每个写操作最终都会落到上游
service 里的 `check_resource_access`，越权的人拿不到 200。

业务逻辑全部在 `src/services/ext/content_tools/`，这一层只做 HTTP 与错误翻译。
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.courses.activities import Activity
from src.db.organizations import Organization
from src.db.users import PublicUser
from src.security.auth import get_current_user
from src.services.ext.content_tools import avatar as avatar_svc
from src.services.ext.content_tools import qrgen
from src.services.ext.content_tools.activities import append_avatar_embed
from src.services.ext.content_tools.avatar import AvatarError
from src.services.ext.content_tools.embeds import EmbedError, resolve_embed
from src.services.ext.content_tools.transfer import (
    MAX_ZIP_BYTES,
    TransferError,
    export_course_markdown,
    import_course_markdown,
)

logger = logging.getLogger(__name__)

router = APIRouter()

#: 二维码内容上限。版本 10 / 等级 M 装得下 213 字节，留点余量给 UTF-8 多字节。
MAX_QR_TEXT_CHARS = 200


# ------------------------------------------------------------ 请求体


class EmbedResolveRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=4000,
                     description="视频页链接、b23.tv 短链，或整段 <iframe> 嵌入代码")


class AvatarAppendRequest(BaseModel):
    script: str = Field(..., min_length=1, max_length=200_000, description="讲稿正文，支持 Markdown")
    title: str | None = Field(None, max_length=200, description="插在数字人上方的小标题，可不填")
    page_url: str | None = Field(None, max_length=2000,
                                 description="临时指定数字人页面地址；不填就按组织配置 → 环境变量 → 默认值")


# ------------------------------------------------------------ 工具


async def _org_config_of_activity(db_session: AsyncSession, activity_uuid: str):
    """取活动所属组织的配置（读不到就返回 None，让 avatar 走环境变量兜底）。"""
    activity = (await db_session.execute(
        select(Activity).where(Activity.activity_uuid == activity_uuid)
    )).scalars().first()
    if not activity:
        return None
    org = (await db_session.execute(
        select(Organization).where(Organization.id == activity.org_id)
    )).scalars().first()
    return _org_config_dict(org)


def _org_config_dict(org):
    if org is None:
        return None
    cfg = getattr(org, "config", None)
    if cfg is None:
        return None
    if isinstance(cfg, dict):
        return cfg
    dump = getattr(cfg, "model_dump", None)
    return dump() if callable(dump) else None


# ------------------------------------------------------------ Markdown 导入导出


@router.post(
    "/courses/{course_uuid}/import-md",
    tags=["ext"],
    summary="从 Markdown 压缩包导入课程内容",
    description=(
        "上传一个「导出 Markdown」生成的 zip（或 skill 的 export-md 目录压成的 zip），"
        "按目录结构新建章节与页面，页内图片一并上传。只还原内容页和整页嵌入，"
        "视频、PDF、作业会在返回的 skipped 里逐条列出。不会覆盖已有内容。"
    ),
    responses={
        200: {"description": "导入完成，返回新建的章节 / 页面与跳过项"},
        400: {"description": "压缩包结构或内容有问题"},
        401: {"description": "需要登录"},
        403: {"description": "对这门课没有创建权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_import_course_markdown(
    *,
    request: Request,
    course_uuid: str,
    file: UploadFile = File(..., description="zip 压缩包"),
    publish: bool | None = Query(None, description="统一指定发布状态；不给就沿用每个 md 头里的 published"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
):
    zip_bytes = await file.read()
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise HTTPException(status_code=400,
                            detail="压缩包超过 %d MB，太大了" % (MAX_ZIP_BYTES // 1024 // 1024))
    try:
        return await import_course_markdown(
            request, course_uuid, zip_bytes, current_user, db_session, publish=publish)
    except TransferError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/courses/{course_uuid}/export-md",
    tags=["ext"],
    summary="把课程导出成 Markdown 压缩包",
    description=(
        "返回一个 zip：README.md（课程信息 + 目录）、按顺序编号的章节目录、"
        "每个活动一个 .md、页内图片放在 assets/。托管视频、PDF、作业只导出占位说明。"
    ),
    responses={
        200: {"description": "zip 文件", "content": {"application/zip": {}}},
        401: {"description": "需要登录"},
        403: {"description": "对这门课没有读取权限"},
        404: {"description": "课程不存在"},
    },
)
async def api_export_course_markdown(
    *,
    request: Request,
    course_uuid: str,
    download_images: bool = Query(True, description="是否把页内图片一起打进包里"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
):
    result = await export_course_markdown(
        request, course_uuid, current_user, db_session, download_images=download_images)
    summary = result["summary"]
    # 文件名里可能有中文，用 RFC 5987 的 filename* 形式，ASCII 那份退回 uuid
    from urllib.parse import quote
    disposition = ("attachment; filename=\"%s.zip\"; filename*=UTF-8''%s"
                   % (course_uuid, quote(result["filename"])))
    return Response(
        content=result["zip_bytes"],
        media_type="application/zip",
        headers={
            "Content-Disposition": disposition,
            "X-Export-Chapters": str(summary["chapters"]),
            "X-Export-Files": str(summary["files"]),
            "X-Export-Images": str(summary["images"]),
            "X-Export-Notes": str(len(summary["notes"])),
        },
    )


# ------------------------------------------------------------ 视频嵌入


@router.post(
    "/embed/resolve",
    tags=["ext"],
    summary="把视频链接规范化成播放器地址",
    description=(
        "bilibili 的七种形态都认（视频页、带分 P、手机版、av 号、b23.tv 短链、"
        "已经是播放器的地址、官方 iframe 代码整段），统一输出 player.bilibili.com 地址。"
        "抖音、腾讯视频原样返回并标 confirmed=false，表示这个站点的 iframe 没有实测过。"
    ),
    responses={
        200: {"description": "{embed_url, provider, confirmed, source_url}"},
        400: {"description": "链接无法解析（短链跳转失败等）"},
        401: {"description": "需要登录"},
    },
)
async def api_resolve_embed(
    *,
    body: EmbedResolveRequest,
    current_user: PublicUser = Depends(get_current_user),
):
    try:
        # resolve_embed 里的短链解析是同步 urllib，不能直接在事件循环里跑
        return await run_in_threadpool(resolve_embed, body.url)
    except EmbedError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------ 虚拟助教


@router.get(
    "/avatar/config",
    tags=["ext"],
    summary="读虚拟助教页面的托管地址",
    description=(
        "按「组织配置 ext 段 → 环境变量 LEARNHOUSE_EXT_AVATAR_PAGE_URL → 内置默认值」"
        "的顺序取，返回值里的 source 说明这次是从哪一层取到的。"
    ),
    responses={
        200: {"description": "{page_url, source}"},
        401: {"description": "需要登录"},
    },
)
async def api_avatar_config(
    *,
    org_id: int | None = Query(None, description="按这个组织的配置来取；不给就只看环境变量和默认值"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
):
    org_config = None
    if org_id is not None:
        org = (await db_session.execute(
            select(Organization).where(Organization.id == org_id)
        )).scalars().first()
        org_config = _org_config_dict(org)
    try:
        return avatar_svc.resolve_page_url(org_config)
    except AvatarError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/activities/{activity_uuid}/avatar",
    tags=["ext"],
    summary="给内容页末尾加一个虚拟助教",
    description=(
        "讲稿会被切成句子、压缩进链接的 hash，页面本身托管在外部静态空间，"
        "所以不占服务器资源也不需要 API key。追加前上游会自动存一条活动版本，"
        "加错了可以在「内容页版本回滚」里撤回。"
    ),
    responses={
        200: {"description": "追加成功，返回数字人链接与句子数"},
        400: {"description": "讲稿为空，或这个活动不是富文本内容页"},
        401: {"description": "需要登录"},
        403: {"description": "对这门课没有修改权限"},
        404: {"description": "活动不存在"},
    },
)
async def api_append_avatar(
    *,
    request: Request,
    activity_uuid: str,
    body: AvatarAppendRequest,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
):
    org_config = await _org_config_of_activity(db_session, activity_uuid)
    try:
        return await append_avatar_embed(
            request, activity_uuid, body.script, current_user, db_session,
            title=body.title, page_url=body.page_url, org_config=org_config)
    except AvatarError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ------------------------------------------------------------ 二维码


@router.get(
    "/qr.svg",
    tags=["ext"],
    summary="生成 SVG 二维码",
    description=(
        "纯标准库编码器（byte 模式 / 纠错等级 M / 版本 1–10），"
        "内容上限 %d 个字符。给邀请码页面把注册链接印成码用。" % MAX_QR_TEXT_CHARS
    ),
    responses={
        200: {"description": "SVG 文本", "content": {"image/svg+xml": {}}},
        400: {"description": "内容为空或太长"},
        401: {"description": "需要登录"},
    },
)
async def api_qr_svg(
    *,
    text: str = Query(..., min_length=1, max_length=MAX_QR_TEXT_CHARS, description="要编码的文本或链接"),
    scale: int = Query(8, ge=1, le=32, description="每个格子的像素边长"),
    caption: str | None = Query(None, max_length=60, description="排在码图下方的说明文字"),
    current_user: PublicUser = Depends(get_current_user),
):
    try:
        matrix, _version, _mask = qrgen.make_matrix(text)
        svg = qrgen.to_svg(matrix, scale=scale, caption=caption)
    except qrgen.QRError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            # 二维码里可能是邀请链接，别让它被当成页面加载
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
        },
    )
