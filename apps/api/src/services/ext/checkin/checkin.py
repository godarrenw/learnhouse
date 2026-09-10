"""上课签到（SYSU-SAM 扩展）的业务逻辑与 RBAC。

路由层只做 HTTP 与依赖注入，权限判断全部在本文件的 ``rbac_check_teacher`` /
``rbac_check_member`` 里。

防作弊只做两层，其余层（网段限制、设备指纹、随机抽查）**未实现**：

1. 登录态绑定 —— 只能给自己签，签到记录的 user_id 取自会话，不接受客户端传入；
2. 动态码 + 短窗口重放限制 —— token/口令每 ``refresh_seconds`` 秒轮换，服务端只接受
   当前窗口与上一窗口；同一账号对同一个 token 只能成功使用一次（Redis SET NX，
   Redis 不可用时降级为数据库唯一约束 ``(session_id, user_id)``）。
"""

import csv
import io
import logging
from datetime import datetime
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.redis import get_redis_client
from src.db.courses.courses import Course
from src.db.ext.checkin import (
    REFRESH_SECONDS_MAX,
    REFRESH_SECONDS_MIN,
    CheckinLiveRead,
    CheckinPublicSessionRead,
    CheckinRecord,
    CheckinRecordRead,
    CheckinSession,
    CheckinSessionCreate,
    CheckinSessionRead,
    CheckinSessionStatus,
    CheckinSubmit,
    CheckinSubmitResult,
)
from src.db.user_organizations import UserOrganization
from src.db.users import AnonymousUser, APITokenUser, InternalUser, PublicUser, User
from src.routers.ext.deps import verify_teacher
from src.security.rbac.rbac import (
    authorization_verify_based_on_roles_and_authorship,
    authorization_verify_if_user_is_anon,
)
from src.services.ext.checkin.tokens import (
    code_for_window,
    current_window,
    generate_secret,
    seconds_remaining,
    token_for_window,
    verify_submission,
)

logger = logging.getLogger(__name__)

RECENT_RECORDS_LIMIT = 20
# 每用户每秒最多提交一次签到
SUBMIT_RATE_LIMIT_WINDOW_SECONDS = 1


# --------------------------------------------------------------------------
# 错误
# --------------------------------------------------------------------------


def _error(status_code: int, code: str, message: str) -> HTTPException:
    """统一的错误体：``detail`` 是 ``{code, message}``。

    前端按 ``code`` 映射 i18n 文案，``message`` 只是兜底的可读英文，
    这样即使走到通用的 ``toast.error(detail)`` 也不会弹出一个对象字面量。
    """
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


# --------------------------------------------------------------------------
# RBAC
# --------------------------------------------------------------------------


async def rbac_check_teacher(
    request: Request,
    course_uuid: str,
    org_id: int,
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    db_session: AsyncSession,
) -> None:
    """教师端两道门。

    第一道是组织级的 ``verify_teacher``（ext 公共依赖，判 Admin / Maintainer /
    Instructor，口径与前端 ``useAdminStatus().isAdmin`` 一致）。这里用的是它的
    非依赖形态 —— 依赖形态 ``require_teacher`` 会强制调用方在 query 里带
    ``org_id``，而签到的每个接口都能从课程或会话反查出组织，没必要让前端多传
    一个可被篡改的参数。

    第二道是课程级的 ``update`` 权限。刻意用 ``update`` 而不是 ``read``：
    课程公开时 ``read`` 对任何登录用户都成立，学生就能拉到全班名单和 IP。
    签到的每一个教师端接口（含只读的实时状态、名单、历史）都按「能改这门课的人」判。

    API token 一律拒绝 —— 签到是课堂现场行为，没有无头集成的场景，
    放开只会扩大攻击面。
    """
    if isinstance(current_user, InternalUser):
        return
    if isinstance(current_user, APITokenUser):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "api_token_not_allowed",
            "API tokens cannot manage check-in sessions.",
        )
    await authorization_verify_if_user_is_anon(current_user.id)
    await verify_teacher(current_user, org_id, db_session)
    await authorization_verify_based_on_roles_and_authorship(
        request, current_user.id, "update", course_uuid, db_session
    )


async def rbac_check_member(
    current_user: PublicUser | AnonymousUser | InternalUser | APITokenUser,
    org_id: int,
    db_session: AsyncSession,
) -> None:
    """学生端：必须是登录用户，且是该组织的成员。"""
    if isinstance(current_user, InternalUser):
        return
    if isinstance(current_user, APITokenUser):
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "api_token_not_allowed",
            "API tokens cannot check in.",
        )
    await authorization_verify_if_user_is_anon(current_user.id)

    statement = select(UserOrganization).where(
        UserOrganization.user_id == current_user.id,
        UserOrganization.org_id == org_id,
    )
    membership = (await db_session.execute(statement)).scalars().first()
    if membership is None:
        raise _error(
            status.HTTP_403_FORBIDDEN,
            "not_org_member",
            "You are not a member of this organization.",
        )


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def client_ip(request: Request) -> str:
    """取客户端 IP。

    优先 ``CF-Connecting-IP``（隧道接入后 Cloudflare 会带这个头，它不可被
    客户端伪造覆盖），其次 ``X-Forwarded-For`` 的第一个，最后落到直连地址。
    """
    cf_ip = (request.headers.get("CF-Connecting-IP") or "").strip()
    if cf_ip:
        return cf_ip[:64]
    forwarded = (request.headers.get("X-Forwarded-For") or "").strip()
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return "unknown"


def _user_agent(request: Request) -> str:
    return (request.headers.get("User-Agent") or "")[:512]


def _now() -> str:
    return str(datetime.now())


async def _get_session_or_404(
    session_uuid: str, db_session: AsyncSession
) -> CheckinSession:
    statement = select(CheckinSession).where(
        CheckinSession.session_uuid == session_uuid
    )
    checkin_session = (await db_session.execute(statement)).scalars().first()
    if checkin_session is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "session_not_found",
            "Check-in session not found.",
        )
    return checkin_session


async def _get_course_or_404(course_uuid: str, db_session: AsyncSession) -> Course:
    statement = select(Course).where(Course.course_uuid == course_uuid)
    course = (await db_session.execute(statement)).scalars().first()
    if course is None:
        raise _error(status.HTTP_404_NOT_FOUND, "course_not_found", "Course not found.")
    return course


async def _get_course_by_id(course_id: int, db_session: AsyncSession) -> Optional[Course]:
    statement = select(Course).where(Course.id == course_id)
    return (await db_session.execute(statement)).scalars().first()


async def _checked_count(session_id: int, db_session: AsyncSession) -> int:
    statement = select(func.count()).select_from(CheckinRecord).where(
        CheckinRecord.session_id == session_id
    )
    return int((await db_session.execute(statement)).scalar() or 0)


async def _to_read(
    checkin_session: CheckinSession, db_session: AsyncSession
) -> CheckinSessionRead:
    course = await _get_course_by_id(checkin_session.course_id, db_session)
    return CheckinSessionRead(
        session_uuid=checkin_session.session_uuid,
        org_id=checkin_session.org_id,
        course_id=checkin_session.course_id,
        course_uuid=course.course_uuid if course else "",
        course_name=course.name if course else "",
        created_by=checkin_session.created_by,
        status=checkin_session.status,
        title=checkin_session.title,
        refresh_seconds=checkin_session.refresh_seconds,
        code_length=checkin_session.code_length,
        started_at=checkin_session.started_at,
        closed_at=checkin_session.closed_at,
        checked_count=await _checked_count(checkin_session.id or 0, db_session),
    )


async def _load_records(
    session_id: int, db_session: AsyncSession, limit: Optional[int] = None
) -> list[CheckinRecordRead]:
    statement = (
        select(CheckinRecord, User)
        .join(User, User.id == CheckinRecord.user_id, isouter=True)
        .where(CheckinRecord.session_id == session_id)
        .order_by(CheckinRecord.id.desc())  # type: ignore[union-attr]
    )
    if limit is not None:
        statement = statement.limit(limit)
    rows = (await db_session.execute(statement)).all()
    records: list[CheckinRecordRead] = []
    for record, user in rows:
        full_name = " ".join(
            part for part in [(user.first_name or ""), (user.last_name or "")] if part
        ).strip() if user else ""
        records.append(
            CheckinRecordRead(
                user_id=record.user_id,
                full_name=full_name or (user.username if user else ""),
                username=user.username if user else "",
                email=user.email if user else "",
                checked_at=record.checked_at,
                method=record.method,
                ip=record.ip,
            )
        )
    return records


# --------------------------------------------------------------------------
# 教师端
# --------------------------------------------------------------------------


async def create_checkin_session(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser,
    course_uuid: str,
    payload: CheckinSessionCreate,
) -> CheckinSessionRead:
    course = await _get_course_or_404(course_uuid, db_session)
    await rbac_check_teacher(
        request, course_uuid, course.org_id, current_user, db_session
    )

    refresh_seconds = int(payload.refresh_seconds)
    if not REFRESH_SECONDS_MIN <= refresh_seconds <= REFRESH_SECONDS_MAX:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_refresh_seconds",
            f"refresh_seconds must be between {REFRESH_SECONDS_MIN} and {REFRESH_SECONDS_MAX}.",
        )

    title = (payload.title or "").strip()
    if not title:
        # 默认「第 N 次课」，N 是该课程已有场次数 + 1
        count_stmt = select(func.count()).select_from(CheckinSession).where(
            CheckinSession.course_id == course.id
        )
        existing = int((await db_session.execute(count_stmt)).scalar() or 0)
        title = f"第 {existing + 1} 次课"
    title = title[:200]

    now = _now()
    checkin_session = CheckinSession(
        session_uuid=f"checkin_{uuid4()}",
        org_id=course.org_id,
        course_id=course.id or 0,
        created_by=current_user.id,
        title=title,
        status=CheckinSessionStatus.OPEN.value,
        refresh_seconds=refresh_seconds,
        secret=generate_secret(),
        started_at=now,
        closed_at=None,
        creation_date=now,
        update_date=now,
    )
    db_session.add(checkin_session)
    await db_session.commit()
    await db_session.refresh(checkin_session)
    return await _to_read(checkin_session, db_session)


async def list_checkin_sessions(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser,
    course_uuid: str,
) -> list[CheckinSessionRead]:
    course = await _get_course_or_404(course_uuid, db_session)
    await rbac_check_teacher(
        request, course_uuid, course.org_id, current_user, db_session
    )

    statement = (
        select(CheckinSession)
        .where(CheckinSession.course_id == course.id)
        .order_by(CheckinSession.id.desc())  # type: ignore[union-attr]
    )
    sessions = (await db_session.execute(statement)).scalars().all()
    return [await _to_read(s, db_session) for s in sessions]


async def get_live_state(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser,
    session_uuid: str,
) -> CheckinLiveRead:
    """投屏页每秒轮询这个接口。

    选轮询而不是 SSE：投屏页只有教师一个人开着，1 秒一次的 JSON 请求量可以忽略，
    而 SSE 在本项目的部署链路（NAS 反代 + 后续的 Cloudflare 隧道）上要额外处理
    缓冲与超时断连，收益不抵成本。
    """
    checkin_session = await _get_session_or_404(session_uuid, db_session)
    course = await _get_course_by_id(checkin_session.course_id, db_session)
    await rbac_check_teacher(
        request,
        course.course_uuid if course else "",
        checkin_session.org_id,
        current_user,
        db_session,
    )

    is_open = checkin_session.status == CheckinSessionStatus.OPEN.value
    window = current_window(checkin_session.refresh_seconds)
    token = (
        token_for_window(checkin_session.secret, session_uuid, window) if is_open else ""
    )
    code = (
        code_for_window(
            checkin_session.secret, session_uuid, window, checkin_session.code_length
        )
        if is_open
        else ""
    )

    return CheckinLiveRead(
        session_uuid=session_uuid,
        title=checkin_session.title,
        course_name=course.name if course else "",
        status=checkin_session.status,
        refresh_seconds=checkin_session.refresh_seconds,
        token=token,
        code=code,
        seconds_remaining=(
            seconds_remaining(checkin_session.refresh_seconds) if is_open else 0
        ),
        checked_count=await _checked_count(checkin_session.id or 0, db_session),
        recent=await _load_records(
            checkin_session.id or 0, db_session, RECENT_RECORDS_LIMIT
        ),
    )


async def close_checkin_session(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser,
    session_uuid: str,
) -> CheckinSessionRead:
    checkin_session = await _get_session_or_404(session_uuid, db_session)
    course = await _get_course_by_id(checkin_session.course_id, db_session)
    await rbac_check_teacher(
        request,
        course.course_uuid if course else "",
        checkin_session.org_id,
        current_user,
        db_session,
    )

    if checkin_session.status != CheckinSessionStatus.CLOSED.value:
        checkin_session.status = CheckinSessionStatus.CLOSED.value
        checkin_session.closed_at = _now()
        checkin_session.update_date = _now()
        db_session.add(checkin_session)
        await db_session.commit()
        await db_session.refresh(checkin_session)

    return await _to_read(checkin_session, db_session)


async def list_checkin_records(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser,
    session_uuid: str,
) -> list[CheckinRecordRead]:
    checkin_session = await _get_session_or_404(session_uuid, db_session)
    course = await _get_course_by_id(checkin_session.course_id, db_session)
    await rbac_check_teacher(
        request,
        course.course_uuid if course else "",
        checkin_session.org_id,
        current_user,
        db_session,
    )
    return await _load_records(checkin_session.id or 0, db_session)


def records_to_csv(
    records: list[CheckinRecordRead], title: str, course_name: str
) -> str:
    """导出 CSV。带 UTF-8 BOM，Excel 打开中文不乱码。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["课程", "场次", "姓名", "邮箱", "签到时间", "方式", "IP"])
    for record in records:
        writer.writerow(
            [
                course_name,
                title,
                record.full_name,
                record.email,
                record.checked_at,
                record.method,
                record.ip,
            ]
        )
    return "﻿" + buffer.getvalue()


# --------------------------------------------------------------------------
# 学生端
# --------------------------------------------------------------------------


async def get_public_session(
    db_session: AsyncSession,
    current_user: PublicUser,
    session_uuid: str,
) -> CheckinPublicSessionRead:
    checkin_session = await _get_session_or_404(session_uuid, db_session)
    await rbac_check_member(current_user, checkin_session.org_id, db_session)
    course = await _get_course_by_id(checkin_session.course_id, db_session)

    existing = (
        await db_session.execute(
            select(CheckinRecord).where(
                CheckinRecord.session_id == checkin_session.id,
                CheckinRecord.user_id == current_user.id,
            )
        )
    ).scalars().first()

    return CheckinPublicSessionRead(
        session_uuid=session_uuid,
        title=checkin_session.title,
        course_uuid=course.course_uuid if course else "",
        course_name=course.name if course else "",
        status=checkin_session.status,
        refresh_seconds=checkin_session.refresh_seconds,
        code_length=checkin_session.code_length,
        already_checked_in=existing is not None,
    )


async def get_open_session_for_course(
    db_session: AsyncSession,
    current_user: PublicUser,
    course_uuid: str,
) -> Optional[CheckinPublicSessionRead]:
    """学生端入口条用：该课程当前是否有开放中的签到。没有则返回 None。"""
    course = await _get_course_or_404(course_uuid, db_session)
    await rbac_check_member(current_user, course.org_id, db_session)

    statement = (
        select(CheckinSession)
        .where(
            CheckinSession.course_id == course.id,
            CheckinSession.status == CheckinSessionStatus.OPEN.value,
        )
        .order_by(CheckinSession.id.desc())  # type: ignore[union-attr]
        .limit(1)
    )
    checkin_session = (await db_session.execute(statement)).scalars().first()
    if checkin_session is None:
        return None
    return await get_public_session(
        db_session, current_user, checkin_session.session_uuid
    )


def _enforce_submit_rate_limit(user_id: int) -> None:
    """每用户每秒 1 次。Redis 不可用时跳过（不因为限流组件缺失就挡住签到）。"""
    redis_client = get_redis_client()
    if redis_client is None:
        return
    try:
        key = f"ext:checkin:submit:{user_id}"
        acquired = redis_client.set(
            key, "1", nx=True, ex=SUBMIT_RATE_LIMIT_WINDOW_SECONDS
        )
    except Exception:
        logger.debug("[checkin] Redis 限流失败，放行", exc_info=True)
        return
    if not acquired:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "rate_limited",
                "message": "Too many attempts. Please wait a second.",
            },
            headers={"Retry-After": str(SUBMIT_RATE_LIMIT_WINDOW_SECONDS)},
        )


def _claim_token_once(
    session_uuid: str, token: str, user_id: int, refresh_seconds: int
) -> bool:
    """把 ``(会话, token, 用户)`` 标记为已使用。

    返回 True 表示这次是首次占用。Redis 不可用时返回 True，此时唯一性完全依赖
    数据库的 ``(session_id, user_id)`` 唯一约束 —— 效果一致（同一账号在一场里
    只能成功一次），只是少了一层快速拒绝。

    注意这里是**每用户**一次而不是全局一次：投屏的二维码在一个窗口内会被全班同学
    同时扫，全局一次会让第二个扫码的人签不上。
    """
    redis_client = get_redis_client()
    if redis_client is None:
        return True
    try:
        key = f"ext:checkin:token:{session_uuid}:{token}:{user_id}"
        return bool(redis_client.set(key, "1", nx=True, ex=2 * refresh_seconds))
    except Exception:
        logger.debug("[checkin] Redis token 占用失败，交给数据库约束", exc_info=True)
        return True


async def submit_checkin(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser,
    session_uuid: str,
    payload: CheckinSubmit,
) -> CheckinSubmitResult:
    checkin_session = await _get_session_or_404(session_uuid, db_session)
    await rbac_check_member(current_user, checkin_session.org_id, db_session)
    _enforce_submit_rate_limit(current_user.id)

    if checkin_session.status != CheckinSessionStatus.OPEN.value:
        raise _error(
            status.HTTP_410_GONE,
            "session_closed",
            "This check-in session is already closed.",
        )

    existing = (
        await db_session.execute(
            select(CheckinRecord).where(
                CheckinRecord.session_id == checkin_session.id,
                CheckinRecord.user_id == current_user.id,
            )
        )
    ).scalars().first()
    if existing is not None:
        raise _error(
            status.HTTP_409_CONFLICT,
            "already_checked_in",
            "You have already checked in for this session.",
        )

    if not (payload.token or payload.code):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "missing_credential",
            "Provide either a token or a code.",
        )

    verified = verify_submission(
        secret=checkin_session.secret,
        session_uuid=session_uuid,
        refresh_seconds=checkin_session.refresh_seconds,
        code_length=checkin_session.code_length,
        token=payload.token,
        code=payload.code,
    )
    if verified is None:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_or_expired_code",
            "The code has expired or is not valid. Look at the screen again.",
        )
    method, token_used = verified

    if not _claim_token_once(
        session_uuid, token_used, current_user.id, checkin_session.refresh_seconds
    ):
        raise _error(
            status.HTTP_409_CONFLICT,
            "already_checked_in",
            "You have already checked in for this session.",
        )

    now = _now()
    record = CheckinRecord(
        session_id=checkin_session.id or 0,
        user_id=current_user.id,
        checked_at=now,
        method=method,
        ip=client_ip(request),
        user_agent=_user_agent(request),
        token_used=token_used,
    )
    db_session.add(record)
    try:
        await db_session.commit()
    except IntegrityError:
        # 并发双击：唯一约束兜住，对用户来说等同于「已签过」
        await db_session.rollback()
        raise _error(
            status.HTTP_409_CONFLICT,
            "already_checked_in",
            "You have already checked in for this session.",
        )

    course = await _get_course_by_id(checkin_session.course_id, db_session)
    return CheckinSubmitResult(
        status="ok",
        method=method,
        checked_at=now,
        course_name=course.name if course else "",
        title=checkin_session.title,
    )
