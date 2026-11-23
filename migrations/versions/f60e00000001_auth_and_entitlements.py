"""User sessions, role records and immutable license entitlement snapshots.

Revision ID: f60e00000001
Revises: d296277344ed
"""
from alembic import op
import sqlalchemy as sa
revision = 'f60e00000001'
down_revision = 'd296277344ed'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('account_access',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('role',sa.String(16),nullable=False),
        sa.Column('disabled',sa.Boolean(),nullable=False))
    op.create_table('auth_sessions',
        sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_auth_sessions_user_id','auth_sessions',['user_id'])
    op.create_index('ix_auth_sessions_expires_at','auth_sessions',['expires_at'])
    op.create_table('license_entitlements',
        sa.Column('grant_id',sa.Integer(),sa.ForeignKey('license_grants.id'),primary_key=True),
        sa.Column('plan_id',sa.String(36),sa.ForeignKey('subscription_plans.id'),nullable=False),
        sa.Column('platform',sa.String(16),nullable=False),
        sa.Column('device_limit',sa.Integer(),nullable=False))

def downgrade():
    raise RuntimeError('Downgrade disabled: restore a tested backup instead of discarding access data')
