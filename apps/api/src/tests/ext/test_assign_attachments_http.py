"""真实 ext 路由 + JWT/课程 RBAC + 本地 SQLite/临时磁盘的 HTTP 回归。"""

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from src.core.events.database import get_db_session
from src.security.auth import JWT_COOKIE_NAME
from src.security.security import ALGORITHM, SECRET_KEY
from src.tests.ext.test_assign_attachments import (
    PDF_BYTES,
    _make_assignment,
    attachment_files,
)

pytestmark = pytest.mark.asyncio
BASE = "/api/v1/ext/assign-attachments"


@pytest.fixture
async def engine(engine, tmp_path):
    # 父夹具负责 JSONB→JSON 映射；独立连接才能真正验证并发事务。
    local = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'attachments.db'}")
    async with local.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield local
    await local.dispose()


@pytest.fixture
async def http_app(engine, tmp_path, monkeypatch):
    from src.router import v1_router

    monkeypatch.chdir(tmp_path)
    # 仅跳过用户活动的后台 Redis 统计，不替换认证或任何权限函数。
    monkeypatch.setattr("src.security.auth._record_activity_from_request", lambda *args: None)
    app = FastAPI()
    app.include_router(v1_router)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def local_session():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = local_session
    return app


def headers(user):
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {"sub": user.email, "iat": now, "exp": now + timedelta(minutes=5),
         "type": "access", "purpose": "session"}, SECRET_KEY, algorithm=ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def assignment(db, org, course, chapter, activity, admin_user, regular_user):
    return await _make_assignment(db, org, course, chapter, activity, published=False)


async def test_http_multipart_permissions_order_download_delete(
    http_app, db, assignment, admin_user, regular_user, tmp_path,
):
    path = f"{BASE}/assignments/{assignment.assignment_uuid}"
    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        teacher = headers(admin_user)
        student = headers(regular_user)
        uploaded = []
        for name in ("第三章作业.pdf", "模板.pdf"):
            response = await client.post(path, headers=teacher, files={"file": (name, PDF_BYTES, "application/pdf")})
            assert response.status_code == 200, response.text
            row = response.json()
            assert row["original_name"] == name
            assert row["size"] == len(PDF_BYTES)
            assert row["download_path"] == f"ext/assign-attachments/{row['attachment_uuid']}/download"
            uploaded.append(row)
        download = f"/api/v1/{uploaded[0]['download_path']}"
        assert (await client.get(path, headers=student)).json() == []
        assert (await client.get(download, headers=student)).status_code == 404
        assert (await client.post(path, headers=student, files={"file": ("x.pdf", PDF_BYTES)})).status_code == 403
        assert (await client.put(f"{path}/order", headers=student, json={"attachment_uuids": []})).status_code == 403
        assert (await client.delete(f"{BASE}/{uploaded[0]['attachment_uuid']}", headers=student)).status_code == 403
        assignment.published = True
        db.add(assignment)
        await db.commit()
        # 浏览器 cookie 认证也经过真实认证链。
        cookie_token = student["Authorization"].removeprefix("Bearer ")
        client.cookies.set(JWT_COOKIE_NAME, cookie_token)
        response = await client.get(path)
        assert [row["original_name"] for row in response.json()] == ["第三章作业.pdf", "模板.pdf"]
        response = await client.get(download)
        assert response.content == PDF_BYTES
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''" + quote("第三章作业.pdf", safe="")
        wanted = [r["attachment_uuid"] for r in reversed(uploaded)]
        response = await client.put(f"{path}/order", headers=teacher, json={"attachment_uuids": wanted})
        assert response.status_code == 200
        assert [r["attachment_uuid"] for r in response.json()] == wanted
        assert [r["position"] for r in response.json()] == [0, 1]
        for invalid in ([wanted[0]], [wanted[0], wanted[0]], ["attachment_foreign", wanted[1]]):
            response = await client.put(f"{path}/order", headers=teacher, json={"attachment_uuids": invalid})
            assert response.status_code == 400
            assert response.json()["detail"]["code"] == "invalid_order"
        response = await client.delete(f"{BASE}/{uploaded[0]['attachment_uuid']}", headers=teacher)
        assert response.json() == {"deleted": uploaded[0]["attachment_uuid"]}
        assert (await client.get(download, headers=teacher)).status_code == 404
        assert len(attachment_files(tmp_path)) == 1


async def test_http_upload_input_validation(http_app, assignment, admin_user, tmp_path, monkeypatch):
    path = f"{BASE}/assignments/{assignment.assignment_uuid}"
    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test", headers=headers(admin_user)) as client:
        response = await client.post(path)
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "no_file"
        for name in ("virus.exe", "picture.svg"):
            assert (await client.post(path, files={"file": (name, PDF_BYTES)})).status_code == 415
        # 用小阈值验证真实 multipart 的大小拒绝，避免测试制造 100MB 内容。
        monkeypatch.setattr("src.services.ext.assign_attachments.MAX_ATTACHMENT_BYTES", len(PDF_BYTES) - 1)
        response = await client.post(path, files={"file": ("large.pdf", PDF_BYTES)})
        assert response.status_code == 413
        assert isinstance(response.json()["detail"], str)
        assert attachment_files(tmp_path) == []
        assert (await client.put(f"{path}/order", json={"attachment_uuids": "wrong"})).status_code == 422
        assert (await client.get(f"{BASE}/assignments/assignment_missing")).status_code == 404


async def test_http_concurrent_uploads_enforce_limit_and_unique_positions(
    http_app, assignment, admin_user, tmp_path, monkeypatch,
):
    import src.services.ext.assign_attachments as service

    path = f"{BASE}/assignments/{assignment.assignment_uuid}"
    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test", headers=headers(admin_user)) as client:
        for i in range(9):
            assert (await client.post(path, files={"file": (f"{i}.pdf", PDF_BYTES)})).status_code == 200
        original_upload = service.upload_file

        async def slow_upload(**kwargs):
            # 扩大“数量检查→提交”间隔，无数据库锁时可稳定重现超额上传。
            await asyncio.sleep(0.05)
            return await original_upload(**kwargs)

        monkeypatch.setattr(service, "upload_file", slow_upload)
        responses = await asyncio.gather(*(
            client.post(path, files={"file": (f"parallel{i}.pdf", PDF_BYTES)}) for i in range(3)
        ))
        assert sorted(r.status_code for r in responses) == [200, 400, 400]
        for response in responses:
            if response.status_code == 400:
                assert response.json()["detail"]["code"] == "too_many_attachments"
        rows = (await client.get(path)).json()
        assert len(rows) == 10
        assert [row["position"] for row in rows] == list(range(10))
        assert len(attachment_files(tmp_path)) == 10


async def test_http_concurrent_append_and_reorder(http_app, assignment, admin_user, monkeypatch):
    import src.services.ext.assign_attachments as service

    path = f"{BASE}/assignments/{assignment.assignment_uuid}"
    original_upload = service.upload_file

    async def slow_upload(**kwargs):
        await asyncio.sleep(0.05)
        return await original_upload(**kwargs)

    monkeypatch.setattr(service, "upload_file", slow_upload)
    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test", headers=headers(admin_user)) as client:
        responses = await asyncio.gather(*(
            client.post(path, files={"file": (f"parallel{i}.pdf", PDF_BYTES)}) for i in range(3)
        ))
        assert [r.status_code for r in responses] == [200, 200, 200]
        rows = (await client.get(path)).json()
        assert [r["position"] for r in rows] == [0, 1, 2]
        wanted = [r["attachment_uuid"] for r in reversed(rows)]
        upload, reorder = await asyncio.gather(
            client.post(path, files={"file": ("new.pdf", PDF_BYTES)}),
            client.put(f"{path}/order", json={"attachment_uuids": wanted}),
        )
        assert upload.status_code == 200
        assert reorder.status_code in (200, 400)
        if reorder.status_code == 400:
            assert reorder.json()["detail"]["code"] == "invalid_order"
        rows = (await client.get(path)).json()
        assert len(rows) == 4
        assert [r["position"] for r in rows] == [0, 1, 2, 3]


async def test_copied_attachments_download_over_http(
    http_app, db, assignment, org, course, chapter, activity, admin_user,
):
    from src.services.ext.assign_attachments import copy_attachments

    path = f"{BASE}/assignments/{assignment.assignment_uuid}"
    async with AsyncClient(transport=ASGITransport(app=http_app), base_url="http://test", headers=headers(admin_user)) as client:
        source = (await client.post(path, files={"file": ("复制题目.pdf", PDF_BYTES)})).json()
        destination = await _make_assignment(db, org, course, chapter, activity, aid=777)
        result = await copy_attachments(db, assignment, destination)
        await db.commit()
        assert result == {"copied": 1, "skipped": []}
        rows = (await client.get(f"{BASE}/assignments/{destination.assignment_uuid}")).json()
        assert len(rows) == 1
        assert rows[0]["original_name"] == source["original_name"]
        assert rows[0]["attachment_uuid"] != source["attachment_uuid"]
        assert (await client.get(f"/api/v1/{rows[0]['download_path']}")).content == PDF_BYTES
        plan = await client.post(f"/api/v1/ext/assign/courses/{course.course_uuid}/clone-term?org_id={org.id}", json={"confirm": False})
        assert plan.status_code == 200, plan.text
        assert [a["attachment_count"] for a in plan.json()["assignments"]] == [1, 1]


async def test_attachment_migration_matches_model(engine, monkeypatch):
    import importlib

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from src.db.ext.assignment_attachments import AssignmentAttachment

    migration = importlib.import_module("migrations.versions.sam2attach01_sysu_sam_assignment_attachments")

    def verify(connection):
        AssignmentAttachment.__table__.drop(connection)
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        migration.upgrade()  # create_all 已建表时也必须幂等
        inspector = sa.inspect(connection)
        columns = inspector.get_columns("assignment_attachment")
        expected = AssignmentAttachment.__table__
        assert {(c["name"], c["nullable"]) for c in columns} == {(c.name, c.nullable) for c in expected.columns}
        assert {(i["name"], tuple(i["column_names"])) for i in inspector.get_indexes("assignment_attachment")} == {(i.name, tuple(c.name for c in i.columns)) for i in expected.indexes}
        assert {(tuple(f["constrained_columns"]), f["referred_table"], f["options"]["ondelete"]) for f in inspector.get_foreign_keys("assignment_attachment")} == {((f.parent.name,), f.column.table.name, f.ondelete) for f in expected.foreign_keys}
        migration.downgrade()
        assert "assignment_attachment" not in sa.inspect(connection).get_table_names()

    async with engine.begin() as connection:
        await connection.run_sync(verify)
