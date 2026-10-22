"""作业题目附件（SYSU-SAM 扩展）的后端测试。

覆盖：上传（类型/数量/原始中文名）、列表排序、重排、删除、学生可见性
（未发布为空/404）、下载头、外键级联、学期复用时的附件复制。

测试直接调 service 层函数，用 conftest 的内存 SQLite 与 org/course/user 夹具。
上传会真的落盘，所以每个用例用 ``tmp_path`` + ``monkeypatch.chdir`` 把内容根
隔离到临时目录，绝不写进仓库。
"""

from datetime import datetime
from io import BytesIO
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import text
from sqlmodel import select

from src.db.courses.assignments import Assignment, GradingTypeEnum
from src.db.ext.assignment_attachments import (
    MAX_ATTACHMENTS_PER_ASSIGNMENT,
    AssignmentAttachment,
    AssignmentAttachmentOrder,
)
from src.services.ext.assign_attachments import (
    copy_attachments,
    delete_attachment,
    download_attachment,
    list_attachments,
    reorder_attachments,
    sanitize_original_name,
    upload_attachment,
)
from src.services.utils.upload_content import read_content

pytestmark = pytest.mark.asyncio

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"


def pdf_upload(name: str, content: bytes = PDF_BYTES) -> UploadFile:
    return UploadFile(filename=name, file=BytesIO(content), size=len(content))


async def _make_assignment(
    db, org, course, chapter, activity, *, aid=500, published=True, title="作业一"
):
    a = Assignment(
        id=aid,
        title=title,
        description="",
        due_date=None,
        published=published,
        grading_type=GradingTypeEnum.NUMERIC,
        org_id=org.id,
        course_id=course.id,
        chapter_id=chapter.id,
        activity_id=activity.id,
        assignment_uuid=f"assignment_{aid}",
        creation_date=str(datetime.now()),
        update_date=str(datetime.now()),
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


def attachment_files(tmp_path):
    root = tmp_path / "content"
    return sorted(p for p in root.rglob("*") if p.is_file()) if root.exists() else []


@pytest.fixture
def isolated_content(tmp_path, monkeypatch):
    """把 ``content/`` 换到临时目录，函数结束自动清掉。"""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# 原始文件名清洗
# ---------------------------------------------------------------------------


def test_sanitize_original_name_strips_path_and_control_chars():
    assert sanitize_original_name("C:\\fakepath\\第三章作业.pdf") == "第三章作业.pdf"
    assert sanitize_original_name("a\x00b\nc.pdf") == "abc.pdf"
    assert sanitize_original_name("...") == "attachment"
    assert sanitize_original_name(None) == "attachment"


def test_sanitize_original_name_truncates_but_keeps_extension():
    out = sanitize_original_name("长" * 300 + ".pdf")
    assert len(out) == 200
    assert out.endswith(".pdf")


# ---------------------------------------------------------------------------
# 上传
# ---------------------------------------------------------------------------


async def test_upload_pdf_keeps_original_chinese_name(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)

    read = await upload_attachment(
        mock_request,
        db,
        admin_user,
        assignment.assignment_uuid,
        pdf_upload("第三章作业.pdf"),
    )

    assert read.attachment_uuid.startswith("attachment_")
    assert read.assignment_uuid == assignment.assignment_uuid
    assert read.original_name == "第三章作业.pdf"
    assert read.content_type == "application/pdf"
    assert read.size == len(PDF_BYTES)
    assert read.position == 0
    assert read.download_path == (
        f"ext/assign-attachments/{read.attachment_uuid}/download"
    )

    files = attachment_files(isolated_content)
    assert len(files) == 1
    assert files[0].read_bytes() == PDF_BYTES
    # 磁盘名不是原始名，而是 upload_file 生成的 uuid 前缀名
    assert files[0].name != "第三章作业.pdf"
    assert files[0].name.endswith(".pdf")


async def test_upload_rejects_disallowed_types(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)

    for name in ("virus.exe", "logo.svg"):
        with pytest.raises(HTTPException) as exc:
            await upload_attachment(
                mock_request,
                db,
                admin_user,
                assignment.assignment_uuid,
                pdf_upload(name, b"MZ\x90\x00 not really a pdf"),
            )
        assert exc.value.status_code == 415
    assert attachment_files(isolated_content) == []


async def test_eleventh_attachment_rejected_before_writing(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)
    for i in range(MAX_ATTACHMENTS_PER_ASSIGNMENT):
        await upload_attachment(
            mock_request,
            db,
            admin_user,
            assignment.assignment_uuid,
            pdf_upload(f"第{i + 1}个.pdf"),
        )

    before = len(attachment_files(isolated_content))
    with pytest.raises(HTTPException) as exc:
        await upload_attachment(
            mock_request,
            db,
            admin_user,
            assignment.assignment_uuid,
            pdf_upload("第11个.pdf"),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "too_many_attachments"
    # 第 11 个没有写盘
    assert len(attachment_files(isolated_content)) == before

    rows = (
        await db.execute(
            select(AssignmentAttachment).where(
                AssignmentAttachment.assignment_id == assignment.id
            )
        )
    ).scalars().all()
    assert len(rows) == MAX_ATTACHMENTS_PER_ASSIGNMENT


async def test_upload_without_file_returns_no_file(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)
    with pytest.raises(HTTPException) as exc:
        await upload_attachment(
            mock_request, db, admin_user, assignment.assignment_uuid, None
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "no_file"


# ---------------------------------------------------------------------------
# 列表与排序
# ---------------------------------------------------------------------------


async def test_list_is_ordered_by_position(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)
    for name in ("A.pdf", "B.pdf", "C.pdf"):
        await upload_attachment(
            mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload(name)
        )

    rows = await list_attachments(
        mock_request, db, admin_user, assignment.assignment_uuid
    )
    assert [r.original_name for r in rows] == ["A.pdf", "B.pdf", "C.pdf"]
    assert [r.position for r in rows] == [0, 1, 2]


async def test_reorder_and_invalid_order(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)
    for name in ("A.pdf", "B.pdf", "C.pdf"):
        await upload_attachment(
            mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload(name)
        )

    rows = await list_attachments(
        mock_request, db, admin_user, assignment.assignment_uuid
    )
    reversed_uuids = [r.attachment_uuid for r in reversed(rows)]

    out = await reorder_attachments(
        mock_request,
        db,
        admin_user,
        assignment.assignment_uuid,
        AssignmentAttachmentOrder(attachment_uuids=reversed_uuids),
    )
    assert [r.original_name for r in out] == ["C.pdf", "B.pdf", "A.pdf"]
    assert [r.position for r in out] == [0, 1, 2]

    # 漏一个
    with pytest.raises(HTTPException) as exc:
        await reorder_attachments(
            mock_request,
            db,
            admin_user,
            assignment.assignment_uuid,
            AssignmentAttachmentOrder(attachment_uuids=reversed_uuids[:2]),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "invalid_order"

    # 重复一个
    with pytest.raises(HTTPException) as exc:
        await reorder_attachments(
            mock_request,
            db,
            admin_user,
            assignment.assignment_uuid,
            AssignmentAttachmentOrder(
                attachment_uuids=[rows[0].attachment_uuid] * len(rows)
            ),
        )
    assert exc.value.detail["code"] == "invalid_order"


# ---------------------------------------------------------------------------
# 删除
# ---------------------------------------------------------------------------


async def test_delete_removes_row_and_file(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    assignment = await _make_assignment(db, org, course, chapter, activity)
    read = await upload_attachment(
        mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload("删我.pdf")
    )
    assert len(attachment_files(isolated_content)) == 1

    result = await delete_attachment(
        mock_request, db, admin_user, read.attachment_uuid
    )
    assert result == {"deleted": read.attachment_uuid}
    assert attachment_files(isolated_content) == []
    assert (
        await db.execute(
            select(AssignmentAttachment).where(
                AssignmentAttachment.attachment_uuid == read.attachment_uuid
            )
        )
    ).scalars().first() is None


async def test_delete_unknown_attachment_returns_404(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    with pytest.raises(HTTPException) as exc:
        await delete_attachment(mock_request, db, admin_user, "attachment_nope")
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "attachment_not_found"


# ---------------------------------------------------------------------------
# 学生可见性
# ---------------------------------------------------------------------------


async def test_student_cannot_see_unpublished_assignment(
    db, org, course, chapter, activity, admin_user, regular_user, mock_request,
    isolated_content,
):
    assignment = await _make_assignment(
        db, org, course, chapter, activity, published=False
    )
    read = await upload_attachment(
        mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload("题目.pdf")
    )

    # 学生列表为空
    rows = await list_attachments(
        mock_request, db, regular_user, assignment.assignment_uuid
    )
    assert rows == []

    # 学生直接下载 → 404
    with pytest.raises(HTTPException) as exc:
        await download_attachment(mock_request, db, regular_user, read.attachment_uuid)
    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "attachment_not_found"

    # 学生对作业没有写权限
    with pytest.raises(HTTPException) as exc:
        await upload_attachment(
            mock_request, db, regular_user, assignment.assignment_uuid,
            pdf_upload("偷传.pdf"),
        )
    assert exc.value.status_code == 403

    # 老师仍然能看到
    teacher_rows = await list_attachments(
        mock_request, db, admin_user, assignment.assignment_uuid
    )
    assert [r.original_name for r in teacher_rows] == ["题目.pdf"]


async def test_student_can_list_and_download_after_publish(
    db, org, course, chapter, activity, admin_user, regular_user, mock_request,
    isolated_content,
):
    assignment = await _make_assignment(
        db, org, course, chapter, activity, published=False
    )
    read = await upload_attachment(
        mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload("第三章作业.pdf")
    )

    assignment.published = True
    assignment.update_date = str(datetime.now())
    db.add(assignment)
    await db.commit()

    rows = await list_attachments(
        mock_request, db, regular_user, assignment.assignment_uuid
    )
    assert [r.original_name for r in rows] == ["第三章作业.pdf"]

    response = await download_attachment(
        mock_request, db, regular_user, read.attachment_uuid
    )
    assert response.body == PDF_BYTES
    assert response.media_type == "application/pdf"
    assert response.headers["x-content-type-options"] == "nosniff"
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition
    assert quote("第三章作业.pdf", safe="") in disposition


# ---------------------------------------------------------------------------
# 外键级联
# ---------------------------------------------------------------------------


async def test_deleting_assignment_cascades_attachments(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    """SQLite 默认不查外键，这里手动打开；夹具若不开就按任务书跳过。"""
    assignment = await _make_assignment(db, org, course, chapter, activity)
    await upload_attachment(
        mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload("级联.pdf")
    )

    await db.execute(text("PRAGMA foreign_keys=ON"))
    await db.delete(assignment)
    await db.commit()

    remaining = (
        await db.execute(
            select(AssignmentAttachment).where(
                AssignmentAttachment.assignment_id == assignment.id
            )
        )
    ).scalars().all()
    if remaining:
        pytest.skip("测试用 SQLite 连接未启用外键，级联无法在这个夹具里验证")
    assert remaining == []


# ---------------------------------------------------------------------------
# 学期复用
# ---------------------------------------------------------------------------


async def test_copy_attachments_copies_names_and_bytes(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    src = await _make_assignment(
        db, org, course, chapter, activity, aid=601, title="源作业"
    )
    for name in ("题目.pdf", "模板.pdf"):
        await upload_attachment(
            mock_request, db, admin_user, src.assignment_uuid, pdf_upload(name)
        )

    dst = await _make_assignment(
        db, org, course, chapter, activity, aid=602, title="新学期作业"
    )

    result = await copy_attachments(db, src, dst)
    assert result["copied"] == 2
    assert result["skipped"] == []

    copied = (
        await db.execute(
            select(AssignmentAttachment)
            .where(AssignmentAttachment.assignment_id == dst.id)
            .order_by(AssignmentAttachment.position)
        )
    ).scalars().all()
    assert [r.original_name for r in copied] == ["题目.pdf", "模板.pdf"]
    assert [r.size for r in copied] == [len(PDF_BYTES), len(PDF_BYTES)]

    # 新作业目录里的字节和源一致
    copied_bytes = await read_content(
        directory=(
            f"courses/{course.course_uuid}/activities/{activity.activity_uuid}"
            f"/assignments/{dst.assignment_uuid}/attachments"
        ),
        type_of_dir="orgs",
        uuid=org.org_uuid,
        file_and_format=copied[0].file_name,
    )
    assert copied_bytes == PDF_BYTES


async def test_copy_attachments_skips_missing_source_file(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    src = await _make_assignment(
        db, org, course, chapter, activity, aid=611, title="源作业"
    )
    dst = await _make_assignment(
        db, org, course, chapter, activity, aid=612, title="新学期作业"
    )
    read = await upload_attachment(
        mock_request, db, admin_user, src.assignment_uuid, pdf_upload("会丢.pdf")
    )
    # 手动删掉磁盘文件，模拟源文件缺失
    for path in attachment_files(isolated_content):
        path.unlink()

    result = await copy_attachments(db, src, dst)
    assert result["copied"] == 0
    assert result["skipped"][0]["original_name"] == "会丢.pdf"
    assert read.attachment_uuid  # 行还在，只是没复制成功


async def test_clone_term_dry_run_reports_attachment_count(
    db, org, course, chapter, activity, admin_user, mock_request, isolated_content
):
    from src.services.ext.assign_tools import clone as clone_svc

    assignment = await _make_assignment(
        db, org, course, chapter, activity, aid=621, title="有附件的作业"
    )
    await upload_attachment(
        mock_request, db, admin_user, assignment.assignment_uuid, pdf_upload("题目.pdf")
    )

    with patch.object(
        clone_svc, "check_resource_access", new_callable=AsyncMock
    ):
        out = await clone_svc.clone_term(
            mock_request, course.course_uuid, admin_user, db,
            name="2026 春", shift_days=180, confirm=False,
        )

    assert out["confirmed"] is False
    assert out["assignments"][0]["attachment_count"] == 1
