"""上课签到（SYSU-SAM 扩展）的后端测试。

覆盖：动态码的窗口边界、一次一用、重复签到、关闭后拒绝、限流、CSV 导出、
RBAC（学生不能开场次、非组织成员不能签到）以及 secret 不外泄。

测试直接调 service 层函数（和仓库里 ``src/tests/services`` 的风格一致），
用 conftest 的内存 SQLite 与 org/course/user 夹具。
"""

import time
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from src.db.ext.checkin import (
    CheckinRecordRead,
    CheckinSessionCreate,
    CheckinSessionStatus,
    CheckinSubmit,
)
from src.services.ext.checkin import tokens as token_utils
from src.services.ext.checkin.checkin import (
    client_ip,
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


def make_request(headers: dict | None = None, client_host: str = "10.0.0.9") -> Request:
    raw_headers = [
        (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": raw_headers,
            "query_string": b"",
            "client": (client_host, 12345),
        }
    )


class FakeRedis:
    """够用的 Redis 替身：只实现 ``set(nx=..., ex=...)``。"""

    def __init__(self):
        self.store: dict[str, float] = {}

    def set(self, key, value, nx=False, ex=None):
        now = time.time()
        expiry = self.store.get(key)
        if expiry is not None and expiry <= now:
            del self.store[key]
            expiry = None
        if nx and expiry is not None:
            return None
        self.store[key] = now + (ex or 60)
        return True


@pytest.fixture
def no_redis():
    """Redis 不可用：限流与 token 占用都降级，唯一性交给数据库约束。"""
    with patch(
        "src.services.ext.checkin.checkin.get_redis_client", return_value=None
    ) as mock:
        yield mock


@pytest.fixture
def fake_redis():
    redis = FakeRedis()
    with patch(
        "src.services.ext.checkin.checkin.get_redis_client", return_value=redis
    ):
        yield redis


async def open_session(db, course, admin_user, refresh_seconds=20):
    return await create_checkin_session(
        make_request(),
        db,
        admin_user,
        course.course_uuid,
        CheckinSessionCreate(title="第 1 次课", refresh_seconds=refresh_seconds),
    )


async def current_token_and_code(db, session_uuid):
    """从数据库里取 secret 自行派生，模拟投屏页当前显示的 token 与口令。"""
    from sqlmodel import select

    from src.db.ext.checkin import CheckinSession

    row = (
        await db.execute(
            select(CheckinSession).where(CheckinSession.session_uuid == session_uuid)
        )
    ).scalars().first()
    window = token_utils.current_window(row.refresh_seconds)
    return (
        token_utils.token_for_window(row.secret, session_uuid, window),
        token_utils.code_for_window(
            row.secret, session_uuid, window, row.code_length
        ),
        row,
    )


# ---------------------------------------------------------------------------
# 纯函数：窗口与派生
# ---------------------------------------------------------------------------


class TestTokenWindows:
    def test_token_and_code_are_stable_within_a_window(self):
        secret = token_utils.generate_secret()
        t1 = token_utils.token_for_window(secret, "s1", 100)
        t2 = token_utils.token_for_window(secret, "s1", 100)
        assert t1 == t2
        assert len(t1) == token_utils.TOKEN_LENGTH

    def test_token_changes_between_windows(self):
        secret = token_utils.generate_secret()
        assert token_utils.token_for_window(
            secret, "s1", 100
        ) != token_utils.token_for_window(secret, "s1", 101)

    def test_code_has_requested_length(self):
        secret = token_utils.generate_secret()
        code = token_utils.code_for_window(secret, "s1", 100, 6)
        assert len(code) == 6 and code.isdigit()

    def test_different_sessions_get_different_tokens(self):
        secret = token_utils.generate_secret()
        assert token_utils.token_for_window(
            secret, "s1", 100
        ) != token_utils.token_for_window(secret, "s2", 100)

    def test_previous_window_is_accepted_current_minus_two_is_not(self):
        secret = token_utils.generate_secret()
        refresh = 20
        now = 20_000.0  # 正好落在窗口 1000 的起点
        window = token_utils.current_window(refresh, now)

        current = token_utils.token_for_window(secret, "s1", window)
        previous = token_utils.token_for_window(secret, "s1", window - 1)
        stale = token_utils.token_for_window(secret, "s1", window - 2)

        common = dict(
            secret=secret,
            session_uuid="s1",
            refresh_seconds=refresh,
            code_length=6,
            now=now,
        )
        assert token_utils.verify_submission(token=current, **common) == (
            "qr",
            current,
        )
        assert token_utils.verify_submission(token=previous, **common) == (
            "qr",
            previous,
        )
        assert token_utils.verify_submission(token=stale, **common) is None

    def test_code_from_previous_window_is_accepted(self):
        secret = token_utils.generate_secret()
        refresh = 30
        now = 30_000.0
        window = token_utils.current_window(refresh, now)
        previous_code = token_utils.code_for_window(secret, "s1", window - 1, 6)
        result = token_utils.verify_submission(
            secret=secret,
            session_uuid="s1",
            refresh_seconds=refresh,
            code_length=6,
            code=previous_code,
            now=now,
        )
        assert result is not None and result[0] == "code"
        # 口令签到也归一化成对应窗口的 token 记录
        assert result[1] == token_utils.token_for_window(secret, "s1", window - 1)

    def test_seconds_remaining_within_window(self):
        assert token_utils.seconds_remaining(20, 20_005.0) == 15
        # 窗口起点返回整个窗口长度，不会返回 0
        assert token_utils.seconds_remaining(20, 20_000.0) == 20


class TestClientIp:
    def test_prefers_cf_connecting_ip(self):
        request = make_request(
            {"CF-Connecting-IP": "203.0.113.7", "X-Forwarded-For": "198.51.100.1"}
        )
        assert client_ip(request) == "203.0.113.7"

    def test_falls_back_to_first_forwarded_for(self):
        request = make_request({"X-Forwarded-For": "198.51.100.1, 10.1.1.1"})
        assert client_ip(request) == "198.51.100.1"

    def test_falls_back_to_direct_peer(self):
        assert client_ip(make_request(client_host="192.0.2.5")) == "192.0.2.5"


# ---------------------------------------------------------------------------
# 会话生命周期
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSessionLifecycle:
    async def test_create_session_is_open_and_hides_secret(
        self, db, org, course, admin_user, no_redis
    ):
        result = await open_session(db, course, admin_user)
        assert result.status == CheckinSessionStatus.OPEN.value
        assert result.course_uuid == course.course_uuid
        assert result.refresh_seconds == 20
        assert result.checked_count == 0
        assert "secret" not in result.model_dump()

    async def test_default_title_counts_existing_sessions(
        self, db, org, course, admin_user, no_redis
    ):
        first = await create_checkin_session(
            make_request(),
            db,
            admin_user,
            course.course_uuid,
            CheckinSessionCreate(title=None, refresh_seconds=20),
        )
        second = await create_checkin_session(
            make_request(),
            db,
            admin_user,
            course.course_uuid,
            CheckinSessionCreate(title="   ", refresh_seconds=20),
        )
        assert first.title == "第 1 次课"
        assert second.title == "第 2 次课"

    @pytest.mark.parametrize("refresh", [9, 121, 0, -5])
    async def test_refresh_seconds_out_of_range_rejected(
        self, db, org, course, admin_user, refresh, no_redis
    ):
        with pytest.raises(HTTPException) as exc:
            await create_checkin_session(
                make_request(),
                db,
                admin_user,
                course.course_uuid,
                CheckinSessionCreate(title="x", refresh_seconds=refresh),
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "invalid_refresh_seconds"

    async def test_live_state_exposes_token_and_code_but_not_secret(
        self, db, org, course, admin_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        live = await get_live_state(
            make_request(), db, admin_user, created.session_uuid
        )
        expected_token, expected_code, row = await current_token_and_code(
            db, created.session_uuid
        )
        assert live.token == expected_token
        assert live.code == expected_code
        assert row.secret not in live.model_dump_json()
        assert 1 <= live.seconds_remaining <= 20

    async def test_close_is_idempotent_and_clears_live_token(
        self, db, org, course, admin_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        closed = await close_checkin_session(
            make_request(), db, admin_user, created.session_uuid
        )
        assert closed.status == CheckinSessionStatus.CLOSED.value
        first_closed_at = closed.closed_at

        again = await close_checkin_session(
            make_request(), db, admin_user, created.session_uuid
        )
        assert again.closed_at == first_closed_at

        live = await get_live_state(
            make_request(), db, admin_user, created.session_uuid
        )
        assert live.token == "" and live.code == ""

    async def test_history_lists_newest_first(
        self, db, org, course, admin_user, no_redis
    ):
        first = await open_session(db, course, admin_user)
        second = await open_session(db, course, admin_user)
        history = await list_checkin_sessions(
            make_request(), db, admin_user, course.course_uuid
        )
        assert [s.session_uuid for s in history] == [
            second.session_uuid,
            first.session_uuid,
        ]

    async def test_unknown_session_is_404(self, db, org, course, admin_user, no_redis):
        with pytest.raises(HTTPException) as exc:
            await get_live_state(make_request(), db, admin_user, "checkin_nope")
        assert exc.value.status_code == 404
        assert exc.value.detail["code"] == "session_not_found"


# ---------------------------------------------------------------------------
# 学生签到
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStudentCheckin:
    async def test_check_in_with_token_succeeds_and_records_ip(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        token, _code, _row = await current_token_and_code(db, created.session_uuid)

        result = await submit_checkin(
            make_request({"CF-Connecting-IP": "203.0.113.9", "User-Agent": "pytest"}),
            db,
            regular_user,
            created.session_uuid,
            CheckinSubmit(token=token),
        )
        assert result.status == "ok"
        assert result.method == "qr"

        records = await list_checkin_records(
            make_request(), db, admin_user, created.session_uuid
        )
        assert len(records) == 1
        assert records[0].user_id == regular_user.id
        assert records[0].ip == "203.0.113.9"
        assert records[0].email == "regular@test.com"

    async def test_check_in_with_code_succeeds(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        _token, code, _row = await current_token_and_code(db, created.session_uuid)

        result = await submit_checkin(
            make_request(), db, regular_user, created.session_uuid, CheckinSubmit(code=code)
        )
        assert result.method == "code"

    async def test_expired_code_is_rejected(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(),
                db,
                regular_user,
                created.session_uuid,
                CheckinSubmit(code="000000", token="deadbeefdeadbeef"),
            )
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "invalid_or_expired_code"

    async def test_missing_credential_is_rejected(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(), db, regular_user, created.session_uuid, CheckinSubmit()
            )
        assert exc.value.detail["code"] == "missing_credential"

    async def test_second_check_in_same_user_is_conflict(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        token, _code, _row = await current_token_and_code(db, created.session_uuid)
        await submit_checkin(
            make_request(), db, regular_user, created.session_uuid, CheckinSubmit(token=token)
        )

        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(),
                db,
                regular_user,
                created.session_uuid,
                CheckinSubmit(token=token),
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "already_checked_in"

    async def test_token_is_single_use_per_user_via_redis(
        self, db, org, course, admin_user, regular_user, fake_redis
    ):
        """Redis 在场时，同一 token 对同一用户只能占用一次。

        占用发生在写库之前，所以即便先把记录删掉，重放同一个 token 也会被挡。
        """
        created = await open_session(db, course, admin_user)
        token, _code, _row = await current_token_and_code(db, created.session_uuid)
        await submit_checkin(
            make_request(), db, regular_user, created.session_uuid, CheckinSubmit(token=token)
        )

        from sqlmodel import delete

        from src.db.ext.checkin import CheckinRecord

        await db.execute(delete(CheckinRecord))
        await db.commit()

        # 放开每秒一次的限流，让这条用例只考察 token 占用本身
        fake_redis.store.pop(f"ext:checkin:submit:{regular_user.id}", None)

        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(),
                db,
                regular_user,
                created.session_uuid,
                CheckinSubmit(token=token),
            )
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "already_checked_in"

    async def test_closed_session_rejects_check_in(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        token, _code, _row = await current_token_and_code(db, created.session_uuid)
        await close_checkin_session(make_request(), db, admin_user, created.session_uuid)

        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(),
                db,
                regular_user,
                created.session_uuid,
                CheckinSubmit(token=token),
            )
        assert exc.value.status_code == 410
        assert exc.value.detail["code"] == "session_closed"

    async def test_rate_limited_to_one_submission_per_second(
        self, db, org, course, admin_user, regular_user, fake_redis
    ):
        created = await open_session(db, course, admin_user)

        # 第一次提交用错误口令，走到限流之后被判无效
        with pytest.raises(HTTPException) as first:
            await submit_checkin(
                make_request(),
                db,
                regular_user,
                created.session_uuid,
                CheckinSubmit(code="000000"),
            )
        assert first.value.detail["code"] == "invalid_or_expired_code"

        # 一秒内再来一次，直接被限流挡掉
        with pytest.raises(HTTPException) as second:
            await submit_checkin(
                make_request(),
                db,
                regular_user,
                created.session_uuid,
                CheckinSubmit(code="000000"),
            )
        assert second.value.status_code == 429
        assert second.value.detail["code"] == "rate_limited"

    async def test_public_view_hides_token_and_reports_already_checked_in(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        public = await get_public_session(db, regular_user, created.session_uuid)
        assert public.already_checked_in is False
        assert "token" not in public.model_dump()
        assert public.course_name == course.name

        token, _code, _row = await current_token_and_code(db, created.session_uuid)
        await submit_checkin(
            make_request(), db, regular_user, created.session_uuid, CheckinSubmit(token=token)
        )
        after = await get_public_session(db, regular_user, created.session_uuid)
        assert after.already_checked_in is True

    async def test_open_session_lookup_for_course(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        assert (
            await get_open_session_for_course(db, regular_user, course.course_uuid)
            is None
        )
        created = await open_session(db, course, admin_user)
        found = await get_open_session_for_course(db, regular_user, course.course_uuid)
        assert found is not None and found.session_uuid == created.session_uuid

        await close_checkin_session(make_request(), db, admin_user, created.session_uuid)
        assert (
            await get_open_session_for_course(db, regular_user, course.course_uuid)
            is None
        )


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPermissions:
    async def test_regular_user_cannot_create_session(
        self, db, org, course, regular_user, no_redis
    ):
        with pytest.raises(HTTPException) as exc:
            await create_checkin_session(
                make_request(),
                db,
                regular_user,
                course.course_uuid,
                CheckinSessionCreate(title="x", refresh_seconds=20),
            )
        assert exc.value.status_code == 403

    async def test_regular_user_cannot_read_records(
        self, db, org, course, admin_user, regular_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        with pytest.raises(HTTPException) as exc:
            await list_checkin_records(
                make_request(), db, regular_user, created.session_uuid
            )
        assert exc.value.status_code == 403

    async def test_anonymous_cannot_check_in(
        self, db, org, course, admin_user, anonymous_user, no_redis
    ):
        created = await open_session(db, course, admin_user)
        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(),
                db,
                anonymous_user,
                created.session_uuid,
                CheckinSubmit(code="000000"),
            )
        assert exc.value.status_code == 403

    async def test_non_member_cannot_check_in(
        self, db, org, other_org, course, admin_user, no_redis
    ):
        """另一个组织里的用户拿到 session_uuid 也签不上（防跨组织 IDOR）。"""
        from datetime import datetime

        from src.db.users import PublicUser, User

        outsider_row = User(
            id=99,
            username="outsider",
            first_name="Out",
            last_name="Sider",
            email="outsider@other.com",
            password="hashed",
            user_uuid="user_outsider",
            creation_date=str(datetime.now()),
            update_date=str(datetime.now()),
        )
        db.add(outsider_row)
        await db.commit()
        outsider = PublicUser(
            id=99,
            username="outsider",
            first_name="Out",
            last_name="Sider",
            email="outsider@other.com",
            user_uuid="user_outsider",
        )

        created = await open_session(db, course, admin_user)
        token, _code, _row = await current_token_and_code(db, created.session_uuid)
        with pytest.raises(HTTPException) as exc:
            await submit_checkin(
                make_request(),
                db,
                outsider,
                created.session_uuid,
                CheckinSubmit(token=token),
            )
        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "not_org_member"


# ---------------------------------------------------------------------------
# CSV 导出
# ---------------------------------------------------------------------------


class TestCsvExport:
    def test_csv_has_bom_header_row_and_data(self):
        rows = [
            CheckinRecordRead(
                user_id=2,
                full_name="张三",
                username="zhangsan",
                email="z@example.com",
                checked_at="2026-09-10 10:00:00",
                method="qr",
                ip="203.0.113.9",
            )
        ]
        csv_text = records_to_csv(rows, "第 1 次课", "测试课程")
        assert csv_text.startswith("﻿")
        lines = csv_text.strip().splitlines()
        assert lines[0].lstrip("﻿") == "课程,场次,姓名,邮箱,签到时间,方式,IP"
        assert "张三" in lines[1]
        assert "203.0.113.9" in lines[1]

    def test_csv_quotes_fields_containing_commas(self):
        rows = [
            CheckinRecordRead(
                user_id=3,
                full_name="Doe, John",
                email="j@example.com",
                checked_at="2026-09-10 10:00:00",
                method="code",
                ip="10.0.0.1",
            )
        ]
        csv_text = records_to_csv(rows, "t", "c")
        assert '"Doe, John"' in csv_text
