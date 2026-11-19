import re
from pathlib import PurePath
from uuid import uuid4

from fastapi import HTTPException, UploadFile
from src.services.utils.upload_content import upload_content, upload_file


HTML_DOCUMENT_DIRECTORY = "documenthtml"
HTML_DOCUMENT_SUFFIX = "_documenthtml.txt"
HTML_DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
_HTML_START = re.compile(r"^\s*<(?:!doctype\s+html\b|!--|[a-z][a-z0-9:-]*[\s/>])", re.I)


async def upload_document(file: UploadFile, activity_uuid: str, org_uuid: str, course_uuid: str) -> str:
    extension = PurePath(file.filename or "").suffix.lower()
    if extension == ".pdf" and file.content_type == "application/pdf":
        return await upload_pdf(file, activity_uuid, org_uuid, course_uuid)
    if extension not in {".html", ".htm"}:
        raise HTTPException(status_code=415, detail="Supported document formats: PDF, HTML (.html, .htm)")

    content = await file.read(HTML_DOCUMENT_MAX_BYTES + 1)
    if len(content) > HTML_DOCUMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="HTML documents must be 20 MB or smaller")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=415, detail="HTML documents must use UTF-8 encoding") from exc
    if "\x00" in text or not _HTML_START.match(text):
        raise HTTPException(status_code=415, detail="Invalid HTML document")

    filename = f"{uuid4().hex}{HTML_DOCUMENT_SUFFIX}"
    await upload_content(
        directory=f"courses/{course_uuid}/activities/{activity_uuid}/{HTML_DOCUMENT_DIRECTORY}",
        type_of_dir="orgs",
        uuid=org_uuid,
        file_binary=content,
        file_and_format=filename,
    )
    return filename


async def upload_pdf(pdf_file: UploadFile, activity_uuid: str, org_uuid: str, course_uuid: str) -> str:
    """Upload a PDF file for a course activity with file validation."""
    return await upload_file(
        file=pdf_file,
        directory=f"courses/{course_uuid}/activities/{activity_uuid}/documentpdf",
        type_of_dir="orgs",
        uuid=org_uuid,
        allowed_types=["document"],
        filename_prefix="documentpdf",
    )
