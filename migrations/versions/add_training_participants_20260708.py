"""Add training_participants table

Revision ID: add_training_participants_20260708
Revises: initial_migration_20250427
Create Date: 2026-07-08 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'add_training_participants_20260708'
down_revision = 'initial_migration_20250427'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'training_participants',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('training_id', sa.Integer(), sa.ForeignKey('trainings.id'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_training_participants_training_id', 'training_participants', ['training_id'])
    op.create_index('ix_training_participants_user_id', 'training_participants', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_training_participants_user_id', table_name='training_participants')
    op.drop_index('ix_training_participants_training_id', table_name='training_participants')
    op.drop_table('training_participants')
