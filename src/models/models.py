from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    Boolean,
    ForeignKey,
    Text,
    Enum as SQLAlchemyEnum,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .base import Base
from .enums import TrainingType, BookingStatus, AdminActionType


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=True)
    vk_id = Column(Integer, unique=True, nullable=True)
    username = Column(String(100), nullable=True)
    first_name = Column(String(100))
    last_name = Column(String(100), nullable=True)
    email = Column(String(255), unique=True, nullable=True)
    phone = Column(String(20), nullable=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bookings = relationship("Booking", back_populates="user")
    payments = relationship("Payment", back_populates="user")


class Training(Base):
    __tablename__ = "trainings"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    training_type = Column(SQLAlchemyEnum(TrainingType), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Monday … 6=Sunday
    start_time = Column(String(5), nullable=False)  # "HH:MM"
    duration_minutes = Column(Integer, default=60)
    max_participants = Column(Integer, nullable=True)  # None = unlimited
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    bookings = relationship("Booking", back_populates="training")
    schedule_entries = relationship("ScheduleEntry", back_populates="training")


class ScheduleEntry(Base):
    __tablename__ = "schedule_entries"

    id = Column(Integer, primary_key=True, index=True)
    training_id = Column(Integer, ForeignKey("trainings.id"), nullable=False)
    date = Column(DateTime(timezone=True), nullable=False)  # конкретная дата+время
    start_time = Column(String(5), nullable=False)  # "HH:MM"
    end_time = Column(String(5), nullable=False)    # "HH:MM"
    is_cancelled = Column(Boolean, default=False)
    cancellation_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    training = relationship("Training", back_populates="schedule_entries")
    bookings = relationship("Booking", back_populates="schedule_entry")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    training_id = Column(Integer, ForeignKey("trainings.id"), nullable=False)
    schedule_entry_id = Column(Integer, ForeignKey("schedule_entries.id"), nullable=True)
    status = Column(
        SQLAlchemyEnum(BookingStatus),
        default=BookingStatus.PENDING,
    )
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    user = relationship("User", back_populates="bookings")
    training = relationship("Training", back_populates="bookings")
    schedule_entry = relationship("ScheduleEntry", back_populates="bookings")
    payment = relationship("Payment", back_populates="booking", uselist=False)


class Payment(Base):
    __tablename__ = "payments"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)  # рублей
    payment_method = Column(String(50), nullable=True)
    is_paid = Column(Boolean, default=False)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    transaction_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    booking = relationship("Booking", back_populates="payment")
    user = relationship("User", back_populates="payments")


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    reminder_time = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    channel = Column(String(20), nullable=False)  # "telegram", "vk"
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    booking = relationship("Booking")


class PublishedSchedule(Base):
    __tablename__ = "published_schedules"

    id = Column(Integer, primary_key=True, index=True)
    week_start_date = Column(DateTime(timezone=True), nullable=False)
    week_end_date = Column(DateTime(timezone=True), nullable=False)
    telegram_message_id = Column(Integer, nullable=True)
    vk_post_id = Column(Integer, nullable=True)
    content = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    action_type = Column(SQLAlchemyEnum(AdminActionType), nullable=False)
    target_id = Column(Integer, nullable=True)
    details = Column(Text, nullable=True)
    performed_at = Column(DateTime(timezone=True), server_default=func.now())

    admin = relationship("User")
