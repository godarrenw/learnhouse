"""上课签到（SYSU-SAM 扩展）路由。

挂载在 ``/api/v1/ext/checkin``。教师端接口要求对课程有 update 权限，
学生端接口只要求是本组织的登录用户。权限判断全在
``src.services.ext.checkin.checkin`` 里，本文件只做 HTTP 与依赖注入。
"""

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.ext.checkin import (
    CheckinLiveRead,
    CheckinPublicSessionRead,
    CheckinRecordRead,
    CheckinSessionCreate,
    CheckinSessionRead,
    CheckinSubmit,
    CheckinSubmitResult,
)
from src.db.users import PublicUser
from src.security.auth import get_current_user
from src.services.ext.checkin.checkin import (
    close_checkin_session,
    create_checkin_session,
    get_live_state,
    get_open_session_for_course,
    get_public_session,
    list_checkin_records,
    list_checkin_sessions,
    records_to_csv,
    submit_checkin,
)

router = APIRouter()


# --------------------------------------------------------------------------
# 教师端
# --------------------------------------------------------------------------


@router.post(
    "/courses/{course_uuid}/sessions",
    response_model=CheckinSessionRead,
    tags=["ext"],
    summary="Start a check-in session for a course",
    description=(
        "Create and immediately open a check-in session. Requires update rights "
        "on the course. The rotating secret is generated server-side and never "
        "returned to any client."
    ),
    responses={
        200: {"description": "Session created and open.", "model": CheckinSessionRead},
        400: {"description": "refresh_seconds out of range"},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Course not found"},
    },
)
async def api_create_checkin_session(
    *,
    request: Request,
    course_uuid: str,
    payload: CheckinSessionCreate,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> CheckinSessionRead:
    return await create_checkin_session(
        request, db_session, current_user, course_uuid, payload
    )


@router.get(
    "/courses/{course_uuid}/sessions",
    response_model=list[CheckinSessionRead],
    tags=["ext"],
    summary="List check-in sessions of a course",
    description="History of check-in sessions for a course, newest first.",
    responses={
        200: {"description": "Sessions listed."},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Course not found"},
    },
)
async def api_list_checkin_sessions(
    *,
    request: Request,
    course_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> list[CheckinSessionRead]:
    return await list_checkin_sessions(request, db_session, current_user, course_uuid)


@router.get(
    "/sessions/{session_uuid}/live",
    response_model=CheckinLiveRead,
    tags=["ext"],
    summary="Live state of a check-in session (projector view)",
    description=(
        "Current QR token, numeric code, seconds left in the window, checked-in "
        "count and the 20 most recent records. Polled once per second by the "
        "projector page."
    ),
    responses={
        200: {"description": "Live state.", "model": CheckinLiveRead},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Session not found"},
    },
)
async def api_get_checkin_live(
    *,
    request: Request,
    session_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> CheckinLiveRead:
    return await get_live_state(request, db_session, current_user, session_uuid)


@router.post(
    "/sessions/{session_uuid}/close",
    response_model=CheckinSessionRead,
    tags=["ext"],
    summary="Close a check-in session",
    description="Closing is idempotent; a closed session rejects further check-ins.",
    responses={
        200: {"description": "Session closed.", "model": CheckinSessionRead},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Session not found"},
    },
)
async def api_close_checkin_session(
    *,
    request: Request,
    session_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> CheckinSessionRead:
    return await close_checkin_session(request, db_session, current_user, session_uuid)


@router.get(
    "/sessions/{session_uuid}/records",
    tags=["ext"],
    summary="Records of a check-in session",
    description=(
        "Returns JSON by default. Pass ``format=csv`` for a UTF-8-BOM CSV "
        "attachment with name, email, timestamp, method and IP."
    ),
    responses={
        200: {"description": "Records listed."},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Session not found"},
    },
)
async def api_list_checkin_records(
    *,
    request: Request,
    session_uuid: str,
    format: str = Query("json", pattern="^(json|csv)$"),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
):
    records: list[CheckinRecordRead] = await list_checkin_records(
        request, db_session, current_user, session_uuid
    )
    if format != "csv":
        return records

    live = await get_live_state(request, db_session, current_user, session_uuid)
    csv_body = records_to_csv(records, live.title, live.course_name)
    return Response(
        content=csv_body,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="checkin_{session_uuid}.csv"'
        },
    )


# --------------------------------------------------------------------------
# 学生端
# --------------------------------------------------------------------------


@router.get(
    "/sessions/{session_uuid}/public",
    response_model=CheckinPublicSessionRead,
    tags=["ext"],
    summary="Public view of a check-in session",
    description=(
        "What a student sees after scanning: title, course, status and whether "
        "they already checked in. Never includes the rotating token."
    ),
    responses={
        200: {"description": "Session info.", "model": CheckinPublicSessionRead},
        401: {"description": "Authentication required"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Session not found"},
    },
)
async def api_get_public_checkin_session(
    *,
    session_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> CheckinPublicSessionRead:
    return await get_public_session(db_session, current_user, session_uuid)


@router.post(
    "/sessions/{session_uuid}/check",
    response_model=CheckinSubmitResult,
    tags=["ext"],
    summary="Check in to a session",
    description=(
        "Binds the check-in to the authenticated user — the client cannot pick "
        "who is checked in. Errors carry a machine-readable ``detail.code``: "
        "``already_checked_in`` (409), ``invalid_or_expired_code`` (400), "
        "``session_closed`` (410), ``rate_limited`` (429)."
    ),
    responses={
        200: {"description": "Checked in.", "model": CheckinSubmitResult},
        400: {"description": "Code expired or invalid"},
        401: {"description": "Authentication required"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Session not found"},
        409: {"description": "Already checked in"},
        410: {"description": "Session closed"},
        429: {"description": "Rate limited"},
    },
)
async def api_submit_checkin(
    *,
    request: Request,
    session_uuid: str,
    payload: CheckinSubmit,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> CheckinSubmitResult:
    return await submit_checkin(
        request, db_session, current_user, session_uuid, payload
    )


@router.get(
    "/my/open",
    tags=["ext"],
    summary="Currently open check-in session for a course",
    description=(
        "Used by the student-facing banner on the course and activity pages. "
        "Returns null when the course has no open session."
    ),
    responses={
        200: {"description": "Open session or null."},
        401: {"description": "Authentication required"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Course not found"},
    },
)
async def api_get_my_open_checkin(
    *,
    course_uuid: str = Query(...),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
):
    return await get_open_session_for_course(db_session, current_user, course_uuid)
