"""GET /api/v1/ext/media/sign —— 给重媒体路径换一个限时签名。

前端在页面里（已登录、带 cookie、同源）调它，把返回的 sig/exp/uid 拼到
媒体域名的地址上；之后的媒体请求本身不需要任何 cookie。

背景与安全边界见 `src/services/ext/media_sign/__init__.py` 的模块文档。
一句话：**签名只表明「请求是谁发的」，能不能看仍由原有 RBAC 在服务时决定。**
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from src.db.users import AnonymousUser, PublicUser
from src.security.auth import get_current_user
from src.services.ext.media_sign import (
    DEFAULT_TTL_SECONDS,
    MAX_TTL_SECONDS,
    MediaSignatureError,
    sign_media_path,
)

router = APIRouter()

# 一次最多签多少条。一个课程页上同时出现的重媒体不会很多（视频活动 1 条 +
# 页内块若干），给 32 足够，同时挡住「拿它当批量预言机刷」的用法。
MAX_BATCH = 32


class SignedMediaUrl(BaseModel):
    path: str
    sig: str
    exp: int
    uid: int


class SignMediaResponse(BaseModel):
    # 与请求里 path 的顺序一一对应
    signatures: List[SignedMediaUrl]
    ttl_seconds: int


@router.get(
    "/media/sign",
    response_model=SignMediaResponse,
    summary="给重媒体路径换限时签名",
    description=(
        "已登录用户用自己的会话换取一组媒体签名，用于访问只在校园网可解析的"
        "媒体域名。签名绑定单个路径、只读、默认 6 小时。"
    ),
    responses={
        400: {"description": "路径不在可签名的重媒体白名单里，或数量超限"},
        401: {"description": "未登录"},
        403: {"description": "API token 不能换签名"},
    },
)
async def sign_media(
    request: Request,
    path: List[str] = Query(
        ...,
        description=(
            "要签名的 URL 路径，可重复传多个。必须是将来实际请求的那个路径形态："
            "以 / 开头、不带 query、percent-encoding 保持原样。"
        ),
    ),
    ttl_seconds: Optional[int] = Query(
        None,
        ge=60,
        le=MAX_TTL_SECONDS,
        description=f"有效期秒数，默认 {DEFAULT_TTL_SECONDS}，上限 {MAX_TTL_SECONDS}",
    ),
    current_user: PublicUser = Depends(get_current_user),
) -> SignMediaResponse:
    # 只签给真人用户。
    # - 匿名：没有身份可绑，而且公开课程本来就不需要签名（匿名直接能取）
    # - API token：它是给脚本用的，脚本可以直接带 Authorization 头访问媒体，
    #   不需要签名；给它签名等于把 token 的权限摊成一堆无法吊销的 URL
    if isinstance(current_user, AnonymousUser) or not getattr(current_user, "id", None):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to sign media URLs",
        )
    if getattr(request.state, "is_api_token", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API tokens cannot exchange media signatures; use the Authorization header directly",
        )

    if len(path) > MAX_BATCH:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Too many paths ({len(path)}); at most {MAX_BATCH} per request",
        )

    ttl = ttl_seconds or DEFAULT_TTL_SECONDS
    signatures: List[SignedMediaUrl] = []
    for p in path:
        try:
            signed = sign_media_path(p, current_user.id, ttl_seconds=ttl)
        except MediaSignatureError as exc:
            # 明确报出是哪条路径不合格，前端好定位；不泄露任何服务端细节。
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot sign path {p!r}: {exc}",
            ) from exc
        signatures.append(SignedMediaUrl(**signed))

    return SignMediaResponse(signatures=signatures, ttl_seconds=ttl)
