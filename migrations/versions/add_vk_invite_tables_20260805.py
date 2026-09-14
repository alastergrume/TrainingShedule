"""Add vk_friends, vk_community_members, vk_invites tables

Revision ID: add_vk_invite_tables_20260805
Revises: add_training_participants_20260708
Create Date: 2026-08-05 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_vk_invite_tables_20260805'
down_revision = 'add_training_participants_20260708'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'vk_friends',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vk_user_id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.String(100), server_default=''),
        sa.Column('last_name', sa.String(100), server_default=''),
        sa.Column('is_deactivated', sa.Boolean(), server_default='false'),
        sa.Column('deactivated_reason', sa.String(20), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vk_friends_id', 'vk_friends', ['id'])
    op.create_index('ix_vk_friends_vk_user_id', 'vk_friends', ['vk_user_id'], unique=True)

    op.create_table(
        'vk_community_members',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vk_user_id', sa.Integer(), nullable=False),
        sa.Column('first_name', sa.String(100), server_default=''),
        sa.Column('last_name', sa.String(100), server_default=''),
        sa.Column('is_deactivated', sa.Boolean(), server_default='false'),
        sa.Column('deactivated_reason', sa.String(20), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vk_community_members_id', 'vk_community_members', ['id'])
    op.create_index('ix_vk_community_members_vk_user_id', 'vk_community_members', ['vk_user_id'], unique=True)

    op.create_table(
        'vk_invites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('friend_id', sa.Integer(), sa.ForeignKey('vk_friends.id'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vk_invites_id', 'vk_invites', ['id'])
    op.create_index('ix_vk_invites_friend_id', 'vk_invites', ['friend_id'])


def downgrade():
    op.drop_table('vk_invites')
    op.drop_table('vk_community_members')
    op.drop_table('vk_friends')
