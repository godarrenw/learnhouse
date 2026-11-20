from html.parser import HTMLParser
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


class PreviewMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.frames = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            self.frames.append(dict(attrs))
        if tag == "script":
            self.scripts.append(dict(attrs))


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

    html = (
        '<!doctype html><h1 title="讲义 &amp; 示例">讲义</h1>'
        "<script>document.title = 'Interactive'</script>"
    ).encode()
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
        static_policy = preview.headers["content-security-policy"]
        assert static_policy.startswith("sandbox; default-src 'none';")
        assert "script-src" not in static_policy
        assert preview.headers["cache-control"] == "private, no-store"

        interactive_params = {"interactive": "true"}
        interactive = await client.get(preview_url, params=interactive_params)
        assert interactive.status_code == 200, interactive.text
        markup = PreviewMarkup()
        markup.feed(interactive.text)
        assert not markup.scripts
        assert markup.frames == [{
            "title": "HTML document",
            "sandbox": "allow-scripts",
            "referrerpolicy": "no-referrer",
            "srcdoc": html.decode(),
        }]
        assert interactive.headers["content-security-policy"] == (
            "sandbox allow-scripts; script-src 'unsafe-inline'; frame-src 'none'; "
            + static_policy.removeprefix("sandbox; ")
        )
        assert interactive.headers["cache-control"] == "private, no-store"

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
        assert (await client.get(preview_url, params=interactive_params)).status_code == 404
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

        second_html = b"<p>Reading notes</p>"
        expanded = await client.put(
            replacement_url,
            files=[
                ("document_files", ("notes.html", second_html, "text/html")),
                ("document_files", ("reference.pdf", b"%PDF-1.4\n", "application/pdf")),
            ],
        )
        assert expanded.status_code == 200, expanded.text
        original, notes, reference = expanded.json()["content"]["documents"]
        assert [item["name"] for item in (original, notes, reference)] == [
            "Handout", "notes.html", "reference.pdf"
        ]
        assert expanded.json()["content"]["filename"] == original["filename"]
        notes_query = {"document": notes["filename"]}
        assert (await client.get(preview_url, params=notes_query)).content == second_html

        other = await client.post(
            "/activities/documentpdf",
            data={"name": "Lab guides", "chapter_id": str(chapter.id)},
            files=[
                ("document_files", ("guide.pdf", b"%PDF-1.4\n", "application/pdf")),
                ("document_files", ("guide.html", b"<p>Lab guide</p>", "text/html")),
            ],
        )
        assert other.status_code == 200, other.text
        other_documents = other.json()["content"]["documents"]
        assert [item["name"] for item in other_documents] == ["guide.pdf", "guide.html"]
        assert (await client.get(
            preview_url, params={"document": other_documents[1]["filename"]}
        )).status_code == 404

        app.dependency_overrides[get_current_user] = AnonymousUser
        assert (await client.get(preview_url, params=notes_query)).status_code == 404
        app.dependency_overrides[get_current_user] = lambda: admin_user

        rejected = await client.put(
            replacement_url, data={"removed_documents": [original["filename"], notes["filename"], reference["filename"]]}
        )
        assert rejected.status_code == 422
        removed = await client.put(
            replacement_url, data={"removed_documents": [original["filename"], notes["filename"]]}
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["content"]["documents"] == [reference]
        assert removed.json()["content"]["filename"] == reference["filename"]
        assert (await client.get(preview_url, params=notes_query)).status_code == 404
