# ============================================================================
# 修改声明（GNU AGPL-3.0 第 5(a) 条）
#
# 本文件是 LearnHouse v1.3.6 的修改版本。
#   上游项目： https://github.com/learnhouse/learnhouse  （tag v1.3.6）
#   修改方：   中山大学先进制造学院 · 先进智造实验室
#   修改日期： 2026-09-08
#   修改摘要： 登录邮件正文中文化，并将品牌名替换为部署方名称。
#
# 上游原始文件见本仓库 git 历史：git show 1.3.6:apps/api/src/services/auth/magic_login.py
# 本平台整体仍以 AGPL-3.0 授权；完整的修改源码获取方式见平台页脚。
# ============================================================================
"""PATCH(nas): 登录邮件正文中文化，品牌名改为「先进智造学堂」。
上游此函数虽然接收 lang 参数，但文案全部硬编码为英文，未使用该参数。
本文件由部署方修改，其余逻辑与上游 LearnHouse 1.3.6 一致。
User-facing passwordless "magic link" login.

Distinct from the admin/integration magic link (``purpose: "magic_link"`` in
:mod:`src.services.admin.admin`), which an API-token integration mints for a
specific user and is delivered out-of-band. This one is requested by the end user
from the login page ("email me a login link"), is emailed by LearnHouse, and
carries ``purpose: "magic_login"``.

Security posture mirrors the admin link:
* short TTL,
* a random ``jti`` enforced single-use via a Redis ``SETNX`` marker at consume,
* consumption goes through :func:`issue_session_or_challenge`, so a user with 2FA
  still gets a second-factor challenge — a magic link is a first factor, not a
  bypass.

The request endpoint never reveals whether an address has an account (always a
200), so it cannot be used to enumerate users.
"""

import html
import logging
import secrets
from datetime import timedelta
from typing import Optional, Tuple
from urllib.parse import quote

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.organizations import Organization
from src.db.users import UserRead
from src.security.auth import create_access_token, decode_jwt
from src.services.email.utils import send_email

logger = logging.getLogger(__name__)

MAGIC_LOGIN_PURPOSE = "magic_login"
# Long enough to leave the app, open email and click; short enough that an
# intercepted-but-unused link expires quickly.
MAGIC_LOGIN_TTL = timedelta(minutes=15)


def issue_magic_login_token(email: str, org_id: Optional[int]) -> str:
    """Mint a single-use magic-login JWT for ``email`` (optionally org-bound)."""
    payload = {
        "sub": email,
        "purpose": MAGIC_LOGIN_PURPOSE,
        "jti": secrets.token_urlsafe(16),
    }
    if org_id is not None:
        payload["org_id"] = org_id
    return create_access_token(data=payload, expires_delta=MAGIC_LOGIN_TTL)


def _redis():  # pragma: no cover - thin import shim; patched out in tests
    try:
        from src.core.redis import get_redis_client

        return get_redis_client()
    except Exception:
        return None


def _burn_jti(jti: str) -> bool:
    """Atomically consume ``jti``. True on first use, False on replay.

    Fails **closed**: if Redis is unavailable we refuse the link rather than risk
    a replayable login. (The admin link fails open because it is already
    single-recipient and integration-gated; a self-service emailed link is a
    softer target, so single-use must hold even without Redis.)
    """
    r = _redis()
    if r is None:
        logger.error("Magic-login: Redis unavailable, refusing to consume (fail closed)")
        return False
    try:
        ok = r.set(
            f"magic_login_used:{jti}",
            "1",
            nx=True,
            ex=int(MAGIC_LOGIN_TTL.total_seconds()) + 60,
        )
        return bool(ok)
    except Exception:
        logger.exception("Magic-login: Redis error during single-use check")
        return False


async def resolve_org(org_slug: Optional[str], db_session: AsyncSession) -> Optional[Organization]:
    if not org_slug:
        return None
    return (
        await db_session.execute(select(Organization).where(Organization.slug == org_slug))
    ).scalars().first()


def send_magic_login_email(
    user: UserRead,
    email: str,
    base_url: str,
    token: str,
    lang: str = "en",
) -> bool:
    """Email the clickable login link. Link points at the frontend consume page,
    which posts the token back to the verify endpoint."""
    from src.services.users.emails import STYLES, _email_layout

    safe_token = quote(token, safe="")
    login_url = f"{base_url.rstrip('/')}/auth/magic?token={safe_token}"
    safe_name = html.escape(user.username or user.email)

    body_content = f"""
        <h1 style="{STYLES['h1']}">登录先进智造学堂</h1>
        <p style="{STYLES['p']}">
            {safe_name} 你好，点击下方按钮即可登录。此链接仅能使用一次，15 分钟后失效。
            如果这不是你本人的操作，忽略本邮件即可。
        </p>
        <a href="{login_url}" style="{STYLES['button']}">立即登录</a>
        <p style="{STYLES['link_text']}">
            如果按钮无法点击，请复制以下链接到浏览器打开：<br />{login_url}
        </p>
    """
    return send_email(
        to=email,
        subject="先进智造学堂登录链接",
        body=_email_layout(
            title="登录先进智造学堂",
            body_content=body_content,
            footer_note="此链接用于登录你的先进智造学堂账户。",
        ),
    )


def consume_magic_login_token(token: str) -> Tuple[str, Optional[int]]:
    """Validate + burn a magic-login token. Returns ``(email, org_id)``.

    Raises 401/410 on an invalid, expired, wrong-purpose, or already-used token.
    """
    try:
        payload = decode_jwt(token)
    except Exception:
        raise HTTPException(status_code=401, detail={"code": "MAGIC_LINK_INVALID", "message": "This login link is invalid or has expired."})

    if not payload or payload.get("purpose") != MAGIC_LOGIN_PURPOSE:
        raise HTTPException(status_code=410, detail={"code": "MAGIC_LINK_INVALID", "message": "This is not a valid login link."})

    jti = payload.get("jti")
    if not jti or not _burn_jti(jti):
        raise HTTPException(
            status_code=410,
            detail={"code": "MAGIC_LINK_USED", "message": "This login link has already been used. Please request a new one."},
        )

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail={"code": "MAGIC_LINK_INVALID", "message": "This login link is invalid."})

    org_raw = payload.get("org_id")
    try:
        org_id = int(org_raw) if org_raw is not None else None
    except (TypeError, ValueError):
        org_id = None
    return str(email), org_id
