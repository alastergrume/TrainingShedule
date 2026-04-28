"""Initial migration

Revision ID: initial_migration_20250427
Revises:
Create Date: 2026-04-27 13:55:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'initial_migration_20250427'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаём enum-типы явно (checkfirst=True — пропустить если уже есть)
    postgresql.ENUM(
        'personal', 'commercial', 'basic', name='trainingtype',
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        'pending', 'confirmed', 'cancelled', 'attended', name='bookingstatus',
    ).create(op.get_bind(), checkfirst=True)

    postgresql.ENUM(
        'create_training', 'update_training', 'delete_training',
        'create_schedule_entry', 'update_schedule_entry', 'cancel_schedule_entry',
        'confirm_booking', 'reject_booking',
        'update_user_admin_status', 'schedule_generated', 'schedule_published',
        name='adminactiontype',
    ).create(op.get_bind(), checkfirst=True)

    # create_type=False — не создавать тип повторно при create_table
    training_type_enum = postgresql.ENUM('personal', 'commercial', 'basic', name='trainingtype', create_type=False)
    booking_status_enum = postgresql.ENUM('pending', 'confirmed', 'cancelled', 'attended', name='bookingstatus', create_type=False)
    admin_action_type_enum = postgresql.ENUM(
        'create_training', 'update_training', 'delete_training',
        'create_schedule_entry', 'update_schedule_entry', 'cancel_schedule_entry',
        'confirm_booking', 'reject_booking',
        'update_user_admin_status', 'schedule_generated', 'schedule_published',
        name='adminactiontype', create_type=False,
    )

    # users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.Integer(), nullable=True),
        sa.Column('vk_id', sa.Integer(), nullable=True),
        sa.Column('username', sa.String(length=100), nullable=True),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_telegram_id'), 'users', ['telegram_id'], unique=True)
    op.create_index(op.f('ix_users_vk_id'), 'users', ['vk_id'], unique=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # trainings (шаблоны тренировок — редактируются администратором)
    op.create_table(
        'trainings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('training_type', training_type_enum, nullable=False),
        sa.Column('day_of_week', sa.Integer(), nullable=False),  # 0=пн … 6=вс
        sa.Column('start_time', sa.String(length=5), nullable=False),
        sa.Column('duration_minutes', sa.Integer(), nullable=True),
        sa.Column('max_participants', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_trainings_id'), 'trainings', ['id'], unique=False)

    # schedule_entries (конкретные занятия на конкретную дату)
    op.create_table(
        'schedule_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('training_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('start_time', sa.String(length=5), nullable=False),
        sa.Column('end_time', sa.String(length=5), nullable=False),
        sa.Column('is_cancelled', sa.Boolean(), nullable=True),
        sa.Column('cancellation_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['training_id'], ['trainings.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_schedule_entries_id'), 'schedule_entries', ['id'], unique=False)
    op.create_index('ix_schedule_entries_date', 'schedule_entries', ['date'], unique=False)

    # bookings
    op.create_table(
        'bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('training_id', sa.Integer(), nullable=False),
        sa.Column('schedule_entry_id', sa.Integer(), nullable=True),
        sa.Column('status', booking_status_enum, nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['schedule_entry_id'], ['schedule_entries.id']),
        sa.ForeignKeyConstraint(['training_id'], ['trainings.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bookings_id'), 'bookings', ['id'], unique=False)

    # payments
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('is_paid', sa.Boolean(), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('transaction_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payments_id'), 'payments', ['id'], unique=False)

    # reminders
    op.create_table(
        'reminders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('booking_id', sa.Integer(), nullable=False),
        sa.Column('reminder_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('channel', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reminders_id'), 'reminders', ['id'], unique=False)

    # published_schedules
    op.create_table(
        'published_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('week_start_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('week_end_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('telegram_message_id', sa.Integer(), nullable=True),
        sa.Column('vk_post_id', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('published_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_published_schedules_id'), 'published_schedules', ['id'], unique=False)

    # admin_actions
    op.create_table(
        'admin_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('admin_id', sa.Integer(), nullable=False),
        sa.Column('action_type', admin_action_type_enum, nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('performed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_admin_actions_id'), 'admin_actions', ['id'], unique=False)


def downgrade() -> None:
    op.drop_table('admin_actions')
    op.drop_table('published_schedules')
    op.drop_table('reminders')
    op.drop_table('payments')
    op.drop_table('bookings')
    op.drop_table('schedule_entries')
    op.drop_table('trainings')
    op.drop_table('users')

    op.execute('DROP TYPE IF EXISTS adminactiontype')
    op.execute('DROP TYPE IF EXISTS bookingstatus')
    op.execute('DROP TYPE IF EXISTS trainingtype')
