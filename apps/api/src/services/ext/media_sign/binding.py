"""把签名换成一个真实的用户对象，供两个媒体路由在鉴权前调用。

单独放一个文件是因为它要碰数据库，而 `signer.py` 刻意保持纯函数便于单测。
"""

from __future__ import annotations

from typing import Union

from fastapi import HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.users import AnonymousUser, PublicUser, User

from .signer import MediaSignatureError, resolve_signed_user_id


async def resolve_signed_user(
    request: Request,
    current_user: Union[PublicUser, AnonymousUser, object],
    db_session: AsyncSession,
):
    """若请求带了有效的媒体签名，返回签名里的用户；否则原样返回 `current_user`。

    行为约定：

    - **没带签名参数** —— 原样返回，调用方完全走原有逻辑，等于本函数不存在。
      这保证了没启用媒体域名的部署（上游默认、本地开发）行为一字不变。
    - **带了但不合法**（过期 / 篡改 / 路径不在白名单）—— 抛 401。
      不静默降级成匿名：那样过期签名会表现成「公开课能看、非公开课 401」，
      现场根本查不出是签名过期。
    - **带了且合法，但请求里同时有真实会话** —— 以真实会话为准，忽略签名。
      同源同用户时两者本来就一致；不一致时（比如换了账号但页面还持有旧签名）
      信会话更符合直觉，也避免「用签名切换身份」这种奇怪的能力。

    拿到用户之后**不做任何权限判断** —— 调用方原有的课程 / 机构检查照常跑，
    只是主语从匿名换成了这个用户。授权仍然在原处发生。
    """
    try:
        signed_uid = resolve_signed_user_id(request.url.path, request.query_params)
    except MediaSignatureError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid media signature: {exc}") from exc

    if signed_uid is None:
        return current_user

    # 有真实会话就以会话为准
    if not isinstance(current_user, AnonymousUser) and getattr(current_user, "id", None):
        return current_user

    user = (
        await db_session.execute(select(User).where(User.id == signed_uid))
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid media signature: unknown user")

    public_user = PublicUser(**user.model_dump())
    # RBAC 里有实现会从 request.state.user 取当前用户，而不是用传进来的参数，
    # 所以这里同步一份，避免「传参是签名用户、state 还是匿名」的错位。
    request.state.user = public_user
    request.state.is_api_token = False
    return public_user
