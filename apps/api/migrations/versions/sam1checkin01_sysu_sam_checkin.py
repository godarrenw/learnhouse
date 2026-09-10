"""[sysu-sam] 上课签到：新增 checkin_session 与 checkin_record 两张表

checkin_session 保存一场课堂签到（含用于派生动态二维码 token 与数字口令的
secret），checkin_record 保存每条签到明细，``(session_id, user_id)`` 唯一，
保证同一账号在一场里只能签到一次。

两个函数都先做存在性检查再动手，和本仓库其它迁移保持一致 —— 生产库是从备份
恢复的，不能假设表一定不存在。

Revision ID: sam1checkin01
Revises: b1c2d3e4f5a6
Create Date: 2026-09-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel  # noqa: F401
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'sam1checkin01'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'checkin_session' not in tables:
        op.create_table(
            'checkin_session',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_uuid', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('org_id', sa.Integer(), nullable=False),
            sa.Column('course_id', sa.Integer(), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=False),
            sa.Column('title', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('refresh_seconds', sa.Integer(), nullable=False),
            sa.Column('code_length', sa.Integer(), nullable=False),
            sa.Column('secret', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('started_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('closed_at', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
            sa.Column('creation_date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('update_date', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.ForeignKeyConstraint(['org_id'], ['organization.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['course_id'], ['course.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(
            'ix_checkin_session_session_uuid', 'checkin_session', ['session_uuid']
        )
        op.create_index('ix_checkin_session_org_id', 'checkin_session', ['org_id'])
        op.create_index('ix_checkin_session_course_id', 'checkin_session', ['course_id'])
        op.create_index(
            'ix_checkin_session_course_status',
            'checkin_session',
            ['course_id', 'status'],
        )

    if 'checkin_record' not in tables:
        op.create_table(
            'checkin_record',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('session_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('checked_at', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('method', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('ip', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.Column('token_used', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
            sa.ForeignKeyConstraint(
                ['session_id'], ['checkin_session.id'], ondelete='CASCADE'
            ),
            sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint(
                'session_id', 'user_id', name='uq_checkin_record_session_user'
            ),
        )
        op.create_index('ix_checkin_record_session', 'checkin_record', ['session_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'checkin_record' in tables:
        op.drop_index('ix_checkin_record_session', table_name='checkin_record')
        op.drop_table('checkin_record')

    if 'checkin_session' in tables:
        op.drop_index('ix_checkin_session_course_status', table_name='checkin_session')
        op.drop_index('ix_checkin_session_course_id', table_name='checkin_session')
        op.drop_index('ix_checkin_session_org_id', table_name='checkin_session')
        op.drop_index('ix_checkin_session_session_uuid', table_name='checkin_session')
        op.drop_table('checkin_session')
