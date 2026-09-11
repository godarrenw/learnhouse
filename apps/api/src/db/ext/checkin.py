"""上课签到（SYSU-SAM 扩展）的数据模型。

两张表：

- ``checkin_session``：一次课堂签到的会话，属于某个组织下的某门课程。
  ``secret`` 是 32 字节随机数的十六进制串，用于派生动态二维码 token 与数字口令，
  **任何对外的读模型都不包含它**。
- ``checkin_record``：一条签到记录。``(session_id, user_id)`` 唯一，保证同一账号
  在同一场次里只能签到一次。

字段风格沿用上游约定：对外主键用 ``<entity>_uuid`` 字符串，时间戳存字符串。
"""

from enum import Enum
from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer, UniqueConstraint
from sqlmodel import Field, SQLModel


class CheckinSessionStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"


class CheckinMethod(str, Enum):
    QR = "qr"
    CODE = "code"


# 刷新间隔的允许区间（秒），前后端与迁移都引用这两个常量
REFRESH_SECONDS_MIN = 10
REFRESH_SECONDS_MAX = 120
REFRESH_SECONDS_DEFAULT = 20
CODE_LENGTH_DEFAULT = 6


class CheckinSessionBase(SQLModel):
    title: str = ""
    refresh_seconds: int = REFRESH_SECONDS_DEFAULT
    code_length: int = CODE_LENGTH_DEFAULT


class CheckinSession(CheckinSessionBase, table=True):
    __tablename__ = "checkin_session"
    __table_args__ = (
        Index("ix_checkin_session_course_status", "course_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    session_uuid: str = Field(default="", index=True)
    org_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("organization.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    course_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("course.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    created_by: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    status: str = Field(default=CheckinSessionStatus.OPEN.value)
    # 32 字节随机数的 hex，永远不出现在读模型里
    secret: str = ""
    started_at: str = ""
    closed_at: Optional[str] = None
    creation_date: str = ""
    update_date: str = ""


class CheckinRecord(SQLModel, table=True):
    __tablename__ = "checkin_record"
    __table_args__ = (
        UniqueConstraint("session_id", "user_id", name="uq_checkin_record_session_user"),
        Index("ix_checkin_record_session", "session_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("checkin_session.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    user_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    checked_at: str = ""
    method: str = CheckinMethod.QR.value
    ip: str = ""
    user_agent: str = ""
    # 本次签到实际使用的 token（口令签到时记录派生出该口令的 token），用于事后审计
    token_used: str = ""


# --------------------------------------------------------------------------
# 入参 / 出参模型
# --------------------------------------------------------------------------


class CheckinSessionCreate(SQLModel):
    title: Optional[str] = None
    refresh_seconds: int = REFRESH_SECONDS_DEFAULT


class CheckinSessionRead(CheckinSessionBase):
    """对外的会话读模型 —— 不含 ``secret``。"""

    session_uuid: str
    org_id: int
    course_id: int
    course_uuid: str = ""
    course_name: str = ""
    created_by: int
    status: str
    started_at: str
    closed_at: Optional[str] = None
    checked_count: int = 0


class CheckinPublicSessionRead(SQLModel):
    """学生扫码后看到的最小信息集，不含任何可用于伪造签到的字段。"""

    session_uuid: str
    title: str
    course_uuid: str
    course_name: str
    status: str
    refresh_seconds: int
    code_length: int
    already_checked_in: bool = False


class CheckinRecordRead(SQLModel):
    user_id: int
    full_name: str = ""
    username: str = ""
    email: str = ""
    checked_at: str = ""
    method: str = ""
    ip: str = ""


class CheckinLiveRead(SQLModel):
    """投屏页轮询用的实时状态。"""

    session_uuid: str
    title: str
    course_name: str
    status: str
    refresh_seconds: int
    token: str
    code: str
    seconds_remaining: int
    checked_count: int
    recent: list[CheckinRecordRead] = []


class CheckinSubmit(SQLModel):
    token: Optional[str] = None
    code: Optional[str] = None


class CheckinSubmitResult(SQLModel):
    status: str = "ok"
    method: str = ""
    checked_at: str = ""
    course_name: str = ""
    title: str = ""
