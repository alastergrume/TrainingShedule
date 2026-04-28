"""Add email column to users table (merged into initial migration)

Revision ID: add_email_to_users
Revises: initial_migration_20250427
Create Date: 2026-04-27 14:01:00.000000

NOTE: email column is now part of the initial migration.
This migration is kept for Alembic chain integrity but performs no operations.
"""
from alembic import op
import sqlalchemy as sa

revision = 'add_email_to_users'
down_revision = 'initial_migration_20250427'
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass  # email already created in initial_migration_20250427


def downgrade() -> None:
    pass
