"""[sysu-sam] 作业题目附件：新增 assignment_attachment 表

老师给一份作业挂多个题目附件（题目 PDF、数据文件、Word 模板），学生能看到作业
就能下载，不受参考答案揭晓规则约束。只新增一张表，不改任何已有表。

和本仓库其它迁移一样先做存在性检查 —— 应用启动时的 create_all 可能已经建过表。

Revision ID: sam2attach01
Revises: sam1checkin01
Create Date: 2026-10-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'sam2attach01'
down_revision: Union[str, None] = 'sam1checkin01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'assignment_attachment' in set(inspector.get_table_names()):
        return

    op.create_table(
        'assignment_attachment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('attachment_uuid', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('org_id', sa.Integer(), nullable=False),
        sa.Column('course_id', sa.Integer(), nullable=False),
        sa.Column('assignment_id', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('file_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('original_name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('content_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('creation_date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('update_date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['course_id'], ['course.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['assignment_id'], ['assignment.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_assignment_attachment_attachment_uuid', 'assignment_attachment', ['attachment_uuid']
    )
    op.create_index('ix_assignment_attachment_org_id', 'assignment_attachment', ['org_id'])
    op.create_index('ix_assignment_attachment_course_id', 'assignment_attachment', ['course_id'])
    op.create_index(
        'ix_assignment_attachment_assignment_id', 'assignment_attachment', ['assignment_id']
    )
    op.create_index(
        'ix_assignment_attachment_assignment_position',
        'assignment_attachment',
        ['assignment_id', 'position'],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if 'assignment_attachment' not in set(inspector.get_table_names()):
        return

    op.drop_index('ix_assignment_attachment_assignment_position', table_name='assignment_attachment')
    op.drop_index('ix_assignment_attachment_assignment_id', table_name='assignment_attachment')
    op.drop_index('ix_assignment_attachment_course_id', table_name='assignment_attachment')
    op.drop_index('ix_assignment_attachment_org_id', table_name='assignment_attachment')
    op.drop_index('ix_assignment_attachment_attachment_uuid', table_name='assignment_attachment')
    op.drop_table('assignment_attachment')
