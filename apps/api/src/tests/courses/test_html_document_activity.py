from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from src.core.events.database import get_db_session
from src.db.courses.activities import Activity, ActivityLockType
from src.db.users import AnonymousUser
from src.routers.courses.activities.activities import router as activities_router
from src.routers.local_content import router as content_router
from src.security.auth import get_current_user


@pytest.mark.asyncio
async def test_html_document_upload_replace_and_preview(
    db, org, course, chapter, admin_user, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "src.services.utils.upload_content.get_learnhouse_config",
        lambda: SimpleNamespace(
            hosting_config=SimpleNamespace(content_delivery=SimpleNamespace(type="filesystem"))
        ),
    )
    for module in ("activities", "pdf"):
        monkeypatch.setattr(
            f"src.services.courses.activities.{module}.check_resource_access", AsyncMock()
        )

    app = FastAPI()
    app.include_router(activities_router, prefix="/activities")
    app.include_router(content_router)
    app.dependency_overrides[get_db_session] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: admin_user

    html = "<!doctype html><h1>讲义</h1>".encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/activities/documentpdf",
            data={"name": "Handout", "chapter_id": str(chapter.id)},
            files={"pdf_file": ("handout.HTML", html, "text/html")},
        )
        assert created.status_code == 200, created.text
        activity = created.json()
        activity_uuid = activity["activity_uuid"]
        preview_url = f"/activities/{activity_uuid}/document-html"
        replacement_url = f"/activities/documentpdf/{activity_uuid}"

        preview = await client.get(preview_url)
        assert preview.status_code == 200, preview.text
        assert preview.content == html
        assert preview.headers["content-type"] == "text/html; charset=utf-8"
        assert preview.headers["content-security-policy"].startswith("sandbox; default-src 'none';")
        assert preview.headers["cache-control"] == "private, no-store"

        raw_url = (
            f"/content/orgs/{org.org_uuid}/courses/{course.course_uuid}/activities/"
            f"{activity_uuid}/documenthtml/{activity['content']['filename']}"
        )
        assert (await client.get(raw_url)).status_code == 404

        row = (await db.execute(select(Activity).where(Activity.activity_uuid == activity_uuid))).scalar_one()
        row.lock_type = ActivityLockType.AUTHENTICATED
        await db.commit()
        app.dependency_overrides[get_current_user] = AnonymousUser
        assert (await client.get(preview_url)).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: admin_user

        invalid = await client.put(
            replacement_url, files={"pdf_file": ("binary.html", b"\x00\xff", "text/html")}
        )
        assert invalid.status_code == 415
        assert (await client.get(preview_url)).content == html

        pdf = await client.put(
            replacement_url, files={"pdf_file": ("handout.pdf", b"%PDF-1.4\n", "application/pdf")}
        )
        assert pdf.status_code == 200, pdf.text
        assert pdf.json()["content"]["filename"].endswith(".pdf")
        assert (await client.get(preview_url)).status_code == 404

        new_html = b"<p>Updated handout</p>"
        replaced = await client.put(
            replacement_url, files={"pdf_file": ("revised.htm", new_html, "application/octet-stream")}
        )
        assert replaced.status_code == 200, replaced.text
        assert (await client.get(preview_url)).content == new_html
