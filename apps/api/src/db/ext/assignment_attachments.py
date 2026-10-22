"""作业题目附件（SYSU-SAM 扩展）的数据模型。

一张表 ``assignment_attachment``：老师挂在一份作业上的题目 PDF、数据文件、
Word 模板等。和上游的「参考答案文件」（``Assignment.solution_file``）不同：

- 一份作业可以挂多个，按 ``position`` 排序；
- **不受 solution_reveal 揭晓规则约束**，学生能看到作业就能下载；
- 保存原始文件名 ``original_name``，下载时用它作文件名，学生拿到的不是一串 uuid。

文件本体放在 ``content/orgs/<org>/courses/<course>/activities/<activity>/
assignments/<assignment>/attachments/`` 下，磁盘上的名字是 ``file_name``
（上游 ``upload_file`` 生成的 ``<uuid>_attachment.<ext>``）。下载一律走
``/api/v1/ext/assign-attachments/<attachment_uuid>/download``，在那里做权限判断。

删除作业时外键级联删掉附件行；磁盘文件和上游参考答案文件一样不清理。
"""

from typing import Optional

from sqlalchemy import Column, ForeignKey, Index, Integer
from sqlmodel import Field, SQLModel

# 每份作业最多挂几个附件，前后端与 lh 命令行都按这个数
MAX_ATTACHMENTS_PER_ASSIGNMENT = 10
# 单个附件的大小上限（字节）。比上游 document 类型的 500MB 收紧：下载接口要
# 整个读进内存再回给浏览器，题目附件也用不到那么大。
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024


class AssignmentAttachment(SQLModel, table=True):
    __tablename__ = "assignment_attachment"
    __table_args__ = (
        Index("ix_assignment_attachment_assignment_position", "assignment_id", "position"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    attachment_uuid: str = Field(default="", index=True)
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
    assignment_id: int = Field(
        sa_column=Column(
            Integer,
            ForeignKey("assignment.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    created_by: Optional[int] = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    # 磁盘上的文件名（不含目录），只在服务端用，不出现在读模型里
    file_name: str = ""
    original_name: str = ""
    content_type: str = ""
    size: int = 0
    position: int = 0
    creation_date: str = ""
    update_date: str = ""


class AssignmentAttachmentRead(SQLModel):
    attachment_uuid: str
    assignment_uuid: str
    original_name: str
    content_type: str
    size: int
    position: int
    creation_date: str
    # 相对 API 根的下载路径，例如 ``ext/assign-attachments/attachment_xxx/download``。
    # 前端拼上 getAPIUrl()，lh 命令行拼上 api_base。
    download_path: str


class AssignmentAttachmentOrder(SQLModel):
    attachment_uuids: list[str]
