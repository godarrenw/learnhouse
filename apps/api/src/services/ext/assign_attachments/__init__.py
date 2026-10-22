"""作业题目附件（SYSU-SAM 扩展）的业务逻辑与 RBAC。

老师给整份作业挂多个题目附件（题目 PDF、数据文件、Word 模板）：学生打开作业
就能下载，**不受参考答案揭晓规则约束**。与上游两种文件的分工：

- ``Assignment.solution_file``：作业级参考答案，受 ``solution_reveal`` 控制；
- ``AssignmentTask.reference_file``：单题参考附件，只出现在那道小题下面；
- 本模块：作业级题目附件，一份作业最多 10 个，按 ``position`` 排序。

权限沿用上游作业的判法：读走 ``AccessAction.READ``，写走 ``AccessAction.UPDATE``
（上传额外用 ``token_action="create"``，与上游 ``put_assignment_solution_file``
一致）。「是不是老师」直接复用上游的 ``_is_assignment_instructor``——学生能看到
作业但作业未发布时，列表返回空、下载返回 404，不泄露题目。

文件本体走上游 ``upload_file`` / ``read_content``，目录与参考答案同一套层级：
``courses/<course>/activities/<activity>/assignments/<assignment>/attachments``，
磁盘名是 ``<uuid>_attachment.<ext>``；读模型里的 ``original_name`` 才是老师上传时
的文件名，下载时用它作 ``Content-Disposition``。
"""

import logging
import os
from datetime import datetime
from typing import Optional
from urllib.parse import quote
from uuid import uuid4

from fastapi import HTTPException, Request, Response, UploadFile, status
from sqlmodel import select, update
from sqlmodel.ext.asyncio.session import AsyncSession

from src.db.courses.activities import Activity
from src.db.courses.assignments import Assignment
from src.db.courses.courses import Course
from src.db.ext.assignment_attachments import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_ASSIGNMENT,
    AssignmentAttachment,
    AssignmentAttachmentOrder,
    AssignmentAttachmentRead,
)
from src.db.organizations import Organization
from src.db.users import AnonymousUser, APITokenUser, PublicUser
from src.security.file_validation import EXT_TO_CANONICAL_MIME, get_safe_filename
from src.security.rbac import AccessAction
from src.services.courses.activities.assignments import (
    _is_assignment_instructor,
    authorize_assignment_access,
)
from src.services.utils.upload_content import read_content, upload_content, upload_file

logger = logging.getLogger(__name__)

# 允许的附件类型：PDF、Word/Excel/PPT（新旧格式）、图片。刻意不含视频与压缩包，
# 题目附件用不到，也能压小单个文件的内存峰值。
ALLOWED_ATTACHMENT_TYPES = ["document", "office", "office_legacy", "image"]

# 原始文件名最多保留这么多个字符（含扩展名）
_MAX_ORIGINAL_NAME_LEN = 200


# --------------------------------------------------------------------------
# 错误
# --------------------------------------------------------------------------


def _error(status_code: int, code: str, message: str) -> HTTPException:
    """统一的错误体：``detail`` 是 ``{code, message}``，与 ext 其它模块一致。"""
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


# --------------------------------------------------------------------------
# 小工具
# --------------------------------------------------------------------------


def _assignment_dir(course_uuid: str, activity_uuid: str, assignment_uuid: str) -> str:
    """附件在内容根下的相对目录。"""
    return (
        f"courses/{course_uuid}/activities/{activity_uuid}"
        f"/assignments/{assignment_uuid}/attachments"
    )


def sanitize_original_name(name: Optional[str]) -> str:
    """清洗上传时的原始文件名。

    去掉路径部分（浏览器偶尔会带 ``C:\\fakepath\\``）与控制字符，长度截到 200
    字符——截断时尽量保留扩展名，否则下载下来系统认不出类型。清洗后为空时退回
    ``attachment``。
    """
    raw = (name or "").replace("\\", "/")
    raw = raw.rsplit("/", 1)[-1]
    # 保留可打印字符，剔除控制字符（含换行、制表、DEL）
    raw = "".join(ch for ch in raw if ch.isprintable()).strip()
    raw = raw.lstrip(".")  # 不允许以点开头，避免生成隐藏文件
    if not raw:
        return "attachment"

    if len(raw) > _MAX_ORIGINAL_NAME_LEN:
        stem, dot, ext = raw.rpartition(".")
        if dot and 0 < len(ext) <= 20:
            keep = _MAX_ORIGINAL_NAME_LEN - len(ext) - 1
            raw = f"{stem[:keep]}.{ext}"
        else:
            raw = raw[:_MAX_ORIGINAL_NAME_LEN]
    return raw or "attachment"


def _content_type_of(upload: UploadFile) -> str:
    """与上游 ``validate_upload`` 同样的口径：先看扩展名的规范 MIME。

    ``upload_file`` 不把校验出来的类型回传，而附件表要存 ``content_type`` 供
    下载头使用。按扩展名查同一张映射表即等价（``validate_upload`` 也是这么算的），
    只有未知扩展名才回落到客户端声明。
    """
    ext = "." + (upload.filename or "").rsplit(".", 1)[-1].lower()
    return EXT_TO_CANONICAL_MIME.get(
        ext, upload.content_type or "application/octet-stream"
    )


def _to_read(
    attachment: AssignmentAttachment, assignment_uuid: str
) -> AssignmentAttachmentRead:
    return AssignmentAttachmentRead(
        attachment_uuid=attachment.attachment_uuid,
        assignment_uuid=assignment_uuid,
        original_name=attachment.original_name,
        content_type=attachment.content_type,
        size=attachment.size,
        position=attachment.position,
        creation_date=attachment.creation_date,
        download_path=f"ext/assign-attachments/{attachment.attachment_uuid}/download",
    )


# --------------------------------------------------------------------------
# 查库
# --------------------------------------------------------------------------


async def _get_assignment_or_404(
    assignment_uuid: str, db_session: AsyncSession
) -> Assignment:
    assignment = (
        await db_session.execute(
            select(Assignment).where(Assignment.assignment_uuid == assignment_uuid)
        )
    ).scalars().first()
    if assignment is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "assignment_not_found",
            "作业不存在。",
        )
    return assignment


async def _get_assignment_by_id_or_404(
    assignment_id: int, db_session: AsyncSession
) -> Assignment:
    assignment = (
        await db_session.execute(
            select(Assignment).where(Assignment.id == assignment_id)
        )
    ).scalars().first()
    if assignment is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "assignment_not_found",
            "作业不存在。",
        )
    return assignment


async def _get_attachment_or_404(
    attachment_uuid: str, db_session: AsyncSession
) -> AssignmentAttachment:
    attachment = (
        await db_session.execute(
            select(AssignmentAttachment).where(
                AssignmentAttachment.attachment_uuid == attachment_uuid
            )
        )
    ).scalars().first()
    if attachment is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "attachment_not_found",
            "附件不存在。",
        )
    return attachment


async def _context_of(
    db_session: AsyncSession, assignment: Assignment
) -> tuple[Activity, Course, Organization]:
    """取附件目录要用到的活动、课程、组织。缺任何一个都按作业不存在处理。"""
    activity = (
        await db_session.execute(
            select(Activity).where(Activity.id == assignment.activity_id)
        )
    ).scalars().first()
    course = (
        await db_session.execute(select(Course).where(Course.id == assignment.course_id))
    ).scalars().first()
    if activity is None or course is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "assignment_not_found",
            "作业不存在。",
        )
    org = (
        await db_session.execute(
            select(Organization).where(Organization.id == course.org_id)
        )
    ).scalars().first()
    if org is None:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "assignment_not_found",
            "作业不存在。",
        )
    return activity, course, org


async def _attachments_of(
    assignment_id: int, db_session: AsyncSession
) -> list[AssignmentAttachment]:
    return list(
        (
            await db_session.execute(
                select(AssignmentAttachment)
                .where(AssignmentAttachment.assignment_id == assignment_id)
                .order_by(
                    AssignmentAttachment.position.asc(),  # type: ignore[union-attr]
                    AssignmentAttachment.id.asc(),  # type: ignore[union-attr]
                )
            )
        ).scalars().all()
    )


async def _lock_attachment_set(db_session: AsyncSession, assignment: Assignment) -> None:
    """串行化同一作业的附件写操作，锁一直持有到事务结束。

    使用不改变字段值的 UPDATE：Postgres 锁住作业行，SQLite 也会取得写锁，
    避免两个上传都通过数量检查，或上传与重排同时产生重复 position。
    """
    await db_session.execute(
        update(Assignment)
        .where(Assignment.id == assignment.id)
        .values(update_date=Assignment.update_date)
        .execution_options(synchronize_session=False)
    )


async def attachment_count_of(assignment_id: int, db_session: AsyncSession) -> int:
    """作业现有附件数，供学期复用的 dry-run 摘要使用。"""
    return len(await _attachments_of(assignment_id, db_session))


async def _is_instructor(
    request: Request,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    course: Course,
    db_session: AsyncSession,
) -> bool:
    """调用者对这门课是否有教师权限（上游口径，按课程 update 判）。"""
    return await _is_assignment_instructor(
        request, current_user, course.course_uuid, db_session
    )


# --------------------------------------------------------------------------
# 读：列表 / 下载
# --------------------------------------------------------------------------


async def list_attachments(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    assignment_uuid: str,
) -> list[AssignmentAttachmentRead]:
    """按 position 升序返回附件列表。

    学生（没有课程 update 权限）在作业未发布时拿到空列表，而不是 403——他能看到
    这门课，但作业还没放出来，附件也不该提前暴露。
    """
    assignment = await _get_assignment_or_404(assignment_uuid, db_session)
    _, course, _ = await _context_of(db_session, assignment)

    await authorize_assignment_access(
        request, db_session, current_user, course.course_uuid, AccessAction.READ
    )

    if not await _is_instructor(request, current_user, course, db_session):
        if not assignment.published:
            return []

    rows = await _attachments_of(assignment.id or 0, db_session)
    return [_to_read(row, assignment.assignment_uuid) for row in rows]


async def download_attachment(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    attachment_uuid: str,
) -> Response:
    """返回文件本体，文件名用原始中文名（RFC 5987 ``filename*``）。"""
    attachment = await _get_attachment_or_404(attachment_uuid, db_session)
    assignment = await _get_assignment_by_id_or_404(
        attachment.assignment_id, db_session
    )
    activity, course, org = await _context_of(db_session, assignment)

    await authorize_assignment_access(
        request, db_session, current_user, course.course_uuid, AccessAction.READ
    )

    if not await _is_instructor(request, current_user, course, db_session):
        if not assignment.published:
            # 不告诉学生「有附件但你不能下」，直接当作不存在
            raise _error(
                status.HTTP_404_NOT_FOUND,
                "attachment_not_found",
                "附件不存在。",
            )

    content = await read_content(
        directory=_assignment_dir(
            course.course_uuid, activity.activity_uuid, assignment.assignment_uuid
        ),
        type_of_dir="orgs",
        uuid=org.org_uuid,
        file_and_format=attachment.file_name,
    )

    quoted_name = quote(attachment.original_name, safe="")
    return Response(
        content=content,
        media_type=attachment.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_name}",
            "X-Content-Type-Options": "nosniff",
            "Content-Length": str(len(content)),
        },
    )


# --------------------------------------------------------------------------
# 写：上传 / 重排 / 删除
# --------------------------------------------------------------------------


async def upload_attachment(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    assignment_uuid: str,
    file: Optional[UploadFile],
) -> AssignmentAttachmentRead:
    """给作业追加一个附件，排在最后。

    校验顺序是刻意的：先判作业/权限，再判文件在不在、数量超没超，**最后才写盘**。
    第 11 个上传被拒时磁盘上不会留下一个没人引用的文件。
    """
    assignment = await _get_assignment_or_404(assignment_uuid, db_session)
    activity, course, org = await _context_of(db_session, assignment)

    await authorize_assignment_access(
        request,
        db_session,
        current_user,
        course.course_uuid,
        AccessAction.UPDATE,
        token_action="create",
    )

    if file is None or not file.filename:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "no_file",
            "没有收到文件。",
        )

    await _lock_attachment_set(db_session, assignment)
    rows = await _attachments_of(assignment.id or 0, db_session)
    if len(rows) >= MAX_ATTACHMENTS_PER_ASSIGNMENT:
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "too_many_attachments",
            f"每份作业最多挂 {MAX_ATTACHMENTS_PER_ASSIGNMENT} 个附件。",
        )

    directory = _assignment_dir(
        course.course_uuid, activity.activity_uuid, assignment.assignment_uuid
    )
    content_type = _content_type_of(file)
    file_name = await upload_file(
        file=file,
        directory=directory,
        type_of_dir="orgs",
        uuid=org.org_uuid,
        allowed_types=ALLOWED_ATTACHMENT_TYPES,
        filename_prefix="attachment",
        max_size=MAX_ATTACHMENT_BYTES,
    )

    now = str(datetime.now())
    attachment = AssignmentAttachment(
        attachment_uuid=f"attachment_{uuid4()}",
        org_id=course.org_id,
        course_id=course.id or 0,
        assignment_id=assignment.id or 0,
        created_by=current_user.id,
        file_name=file_name,
        original_name=sanitize_original_name(file.filename),
        content_type=content_type,
        size=_stored_size(org.org_uuid, directory, file_name, file),
        position=max((row.position for row in rows), default=-1) + 1,
        creation_date=now,
        update_date=now,
    )
    db_session.add(attachment)
    await db_session.commit()
    await db_session.refresh(attachment)
    return _to_read(attachment, assignment.assignment_uuid)


async def reorder_attachments(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    assignment_uuid: str,
    payload: AssignmentAttachmentOrder,
) -> list[AssignmentAttachmentRead]:
    """按给定的顺序重排。

    ``attachment_uuids`` 必须**恰好**是现有附件的一个排列（不重不漏），否则 400
    ``invalid_order``——这样既挡住跨作业的 uuid，也挡住漏传导致 position 撞车。
    """
    assignment = await _get_assignment_or_404(assignment_uuid, db_session)
    _, course, _ = await _context_of(db_session, assignment)

    await authorize_assignment_access(
        request, db_session, current_user, course.course_uuid, AccessAction.UPDATE
    )

    await _lock_attachment_set(db_session, assignment)
    rows = await _attachments_of(assignment.id or 0, db_session)
    by_uuid = {row.attachment_uuid: row for row in rows}
    wanted = list(payload.attachment_uuids or [])
    if (
        len(wanted) != len(rows)
        or len(set(wanted)) != len(wanted)
        or set(wanted) != set(by_uuid)
    ):
        raise _error(
            status.HTTP_400_BAD_REQUEST,
            "invalid_order",
            "附件顺序必须恰好包含这份作业的全部附件。",
        )

    now = str(datetime.now())
    for position, attachment_uuid in enumerate(wanted):
        row = by_uuid[attachment_uuid]
        row.position = position
        row.update_date = now
        db_session.add(row)

    await db_session.commit()
    rows = await _attachments_of(assignment.id or 0, db_session)
    return [_to_read(row, assignment.assignment_uuid) for row in rows]


async def delete_attachment(
    request: Request,
    db_session: AsyncSession,
    current_user: PublicUser | AnonymousUser | APITokenUser,
    attachment_uuid: str,
) -> dict:
    """删除附件行，并尽力删掉磁盘文件（删不掉只记日志，不回滚删除）。"""
    attachment = await _get_attachment_or_404(attachment_uuid, db_session)
    assignment = await _get_assignment_by_id_or_404(
        attachment.assignment_id, db_session
    )
    activity, course, org = await _context_of(db_session, assignment)

    await authorize_assignment_access(
        request, db_session, current_user, course.course_uuid, AccessAction.UPDATE
    )

    directory = _assignment_dir(
        course.course_uuid, activity.activity_uuid, assignment.assignment_uuid
    )
    file_name = attachment.file_name

    await _lock_attachment_set(db_session, assignment)
    await db_session.delete(attachment)
    await db_session.commit()

    # 行删了才算成功；文件删除失败不影响接口结果
    await _delete_stored_file(
        org_uuid=org.org_uuid, directory=directory, file_name=file_name
    )
    return {"deleted": attachment_uuid}


# --------------------------------------------------------------------------
# 磁盘 / S3 辅助
# --------------------------------------------------------------------------


def _delivery_is_filesystem() -> bool:
    from config.config import get_learnhouse_config

    return get_learnhouse_config().hosting_config.content_delivery.type == "filesystem"


def _content_path(org_uuid: str, directory: str, file_name: str) -> str:
    """本地内容文件的绝对路径，带越界检查（file_name 是服务端生成的，仍防守）。"""
    base = os.path.realpath("content")
    full = os.path.realpath(os.path.join(base, "orgs", org_uuid, directory, file_name))
    try:
        contained = os.path.commonpath([base, full]) == base
    except ValueError:
        contained = False
    if not contained:
        raise _error(
            status.HTTP_400_BAD_REQUEST, "invalid_path", "文件路径不合法。"
        )
    return full


def _stored_size(
    org_uuid: str, directory: str, file_name: str, upload: UploadFile
) -> int:
    """附件字节数。文件系统下以落盘后的实际大小为准，S3 下用上传流的大小。"""
    if _delivery_is_filesystem():
        try:
            return os.path.getsize(_content_path(org_uuid, directory, file_name))
        except Exception:
            pass
    return int(getattr(upload, "size", 0) or 0)


async def _delete_stored_file(org_uuid: str, directory: str, file_name: str) -> None:
    """尽力删除已存文件。任何异常都只记日志，不影响删除附件的返回。"""
    try:
        if _delivery_is_filesystem():
            path = _content_path(org_uuid, directory, file_name)
            if os.path.exists(path):
                os.remove(path)
            return

        # s3api：删对象；失败同样只记日志
        import asyncio

        import boto3
        import botocore.config

        from config.config import get_learnhouse_config

        config = get_learnhouse_config().hosting_config.content_delivery.s3api
        s3 = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url,
            config=botocore.config.Config(
                connect_timeout=10, read_timeout=60, retries={"max_attempts": 2}
            ),
        )
        bucket = config.bucket_name or "learnhouse-media"
        key = f"content/orgs/{org_uuid}/{directory}/{file_name}"
        await asyncio.to_thread(s3.delete_object, Bucket=bucket, Key=key)
    except Exception:
        logger.warning(
            "[assign_attachments] 删除磁盘文件失败：%s/%s/%s",
            org_uuid,
            directory,
            file_name,
            exc_info=True,
        )


# --------------------------------------------------------------------------
# 学期复用
# --------------------------------------------------------------------------


async def copy_attachments(
    db_session: AsyncSession,
    src_assignment: Assignment,
    dst_assignment: Assignment,
) -> dict:
    """把源作业的附件复制到新作业。

    读源文件字节、按新磁盘名（新 uuid）写到新作业目录，再插入新行。源文件读不到
    时跳过该附件并在返回值 ``skipped`` 里列出，不打断整个克隆。

    返回 ``{"copied": int, "skipped": [{"original_name": str, "reason": str}]}``。
    """
    result: dict = {"copied": 0, "skipped": []}

    try:
        src_activity, src_course, src_org = await _context_of(db_session, src_assignment)
        dst_activity, dst_course, dst_org = await _context_of(db_session, dst_assignment)
    except HTTPException:
        result["skipped"].append(
            {"original_name": "", "reason": "找不到源或目标作业的课程/活动"}
        )
        return result

    src_dir = _assignment_dir(
        src_course.course_uuid, src_activity.activity_uuid, src_assignment.assignment_uuid
    )
    dst_dir = _assignment_dir(
        dst_course.course_uuid, dst_activity.activity_uuid, dst_assignment.assignment_uuid
    )

    now = str(datetime.now())
    for row in await _attachments_of(src_assignment.id or 0, db_session):
        try:
            content = await read_content(
                directory=src_dir,
                type_of_dir="orgs",
                uuid=src_org.org_uuid,
                file_and_format=row.file_name,
            )
        except HTTPException as exc:
            result["skipped"].append(
                {
                    "original_name": row.original_name,
                    "reason": f"源文件读取失败（HTTP {exc.status_code}）",
                }
            )
            continue

        new_file_name = get_safe_filename(
            row.original_name, f"{uuid4()}_attachment", content_type=row.content_type
        )
        try:
            await upload_content(
                directory=dst_dir,
                type_of_dir="orgs",
                uuid=dst_org.org_uuid,
                file_binary=content,
                file_and_format=new_file_name,
            )
        except Exception as exc:  # 写盘失败也跳过，不拖垮克隆
            logger.warning(
                "[assign_attachments] 复制附件写盘失败：%s", row.original_name, exc_info=True
            )
            result["skipped"].append(
                {
                    "original_name": row.original_name,
                    "reason": f"写盘失败：{exc.__class__.__name__}",
                }
            )
            continue

        db_session.add(
            AssignmentAttachment(
                attachment_uuid=f"attachment_{uuid4()}",
                org_id=dst_course.org_id,
                course_id=dst_course.id or 0,
                assignment_id=dst_assignment.id or 0,
                created_by=row.created_by,
                file_name=new_file_name,
                original_name=row.original_name,
                content_type=row.content_type,
                size=len(content),
                position=row.position,
                creation_date=now,
                update_date=now,
            )
        )
        result["copied"] += 1

    await db_session.flush()
    return result
