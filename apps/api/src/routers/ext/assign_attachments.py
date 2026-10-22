"""作业题目附件（SYSU-SAM 扩展）路由。

挂载在 ``/api/v1/ext/assign-attachments``。权限按作业所属课程判定，
不加 ``?org_id=`` 之类的可篡改参数。读接口要求课程 READ，写接口要求课程 UPDATE，
具体逻辑全在 ``src.services.ext.assign_attachments`` 里，本文件只做 HTTP 与依赖注入。
"""

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.db.ext.assignment_attachments import (
    AssignmentAttachmentOrder,
    AssignmentAttachmentRead,
)
from src.db.users import PublicUser
from src.security.auth import get_current_user
from src.services.ext.assign_attachments import (
    delete_attachment,
    download_attachment,
    list_attachments,
    reorder_attachments,
    upload_attachment,
)

router = APIRouter()


@router.get(
    "/assignments/{assignment_uuid}",
    response_model=list[AssignmentAttachmentRead],
    tags=["ext"],
    summary="List attachments of an assignment",
    description=(
        "Returns the assignment's attachments ordered by position. A caller "
        "without instructor rights on the course gets an empty list while the "
        "assignment is unpublished."
    ),
    responses={
        200: {"description": "Attachments listed."},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Assignment not found"},
    },
)
async def api_list_attachments(
    *,
    request: Request,
    assignment_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> list[AssignmentAttachmentRead]:
    return await list_attachments(
        request, db_session, current_user, assignment_uuid
    )


@router.post(
    "/assignments/{assignment_uuid}",
    response_model=AssignmentAttachmentRead,
    tags=["ext"],
    summary="Upload one attachment to an assignment",
    description=(
        "Multipart upload with a single file in the ``file`` field. The new "
        "attachment is placed last. At most 10 attachments per assignment; "
        "uploading the 11th returns 400 ``too_many_attachments`` without "
        "writing anything to disk."
    ),
    responses={
        200: {"description": "Attachment created.", "model": AssignmentAttachmentRead},
        400: {"description": "No file, or the 10-attachment limit is reached"},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Assignment not found"},
        413: {"description": "File larger than 100MB"},
        415: {"description": "File type not allowed"},
    },
)
async def api_upload_attachment(
    *,
    request: Request,
    assignment_uuid: str,
    file: UploadFile | None = File(None),
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> AssignmentAttachmentRead:
    return await upload_attachment(
        request, db_session, current_user, assignment_uuid, file
    )


@router.put(
    "/assignments/{assignment_uuid}/order",
    response_model=list[AssignmentAttachmentRead],
    tags=["ext"],
    summary="Reorder an assignment's attachments",
    description=(
        "Body ``{\"attachment_uuids\": [...]}`` must be exactly a permutation of "
        "the assignment's current attachments, otherwise 400 ``invalid_order``."
    ),
    responses={
        200: {"description": "Attachments reordered."},
        400: {"description": "The list is not a permutation of existing attachments"},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Assignment not found"},
    },
)
async def api_reorder_attachments(
    *,
    request: Request,
    assignment_uuid: str,
    payload: AssignmentAttachmentOrder,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> list[AssignmentAttachmentRead]:
    return await reorder_attachments(
        request, db_session, current_user, assignment_uuid, payload
    )


@router.delete(
    "/{attachment_uuid}",
    tags=["ext"],
    summary="Delete an attachment",
    description=(
        "Deletes the row and best-effort removes the stored file (a failed "
        "file removal is only logged)."
    ),
    responses={
        200: {"description": "Attachment deleted."},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Attachment not found"},
    },
)
async def api_delete_attachment(
    *,
    request: Request,
    attachment_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> dict:
    return await delete_attachment(
        request, db_session, current_user, attachment_uuid
    )


@router.get(
    "/{attachment_uuid}/download",
    tags=["ext"],
    summary="Download an attachment",
    description=(
        "Returns the file with its stored content type and the original "
        "filename in ``Content-Disposition`` (RFC 5987, UTF-8). Students get a "
        "404 while the assignment is unpublished."
    ),
    responses={
        200: {"description": "File bytes."},
        401: {"description": "Authentication required"},
        403: {"description": "User lacks permission on this course"},
        404: {"description": "Attachment not found, or assignment unpublished"},
    },
)
async def api_download_attachment(
    *,
    request: Request,
    attachment_uuid: str,
    db_session: AsyncSession = Depends(get_db_session),
    current_user: PublicUser = Depends(get_current_user),
) -> Response:
    return await download_attachment(
        request, db_session, current_user, attachment_uuid
    )
