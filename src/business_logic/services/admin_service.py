from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, update
import logging

from src.models import (
    Training,
    TrainingParticipant,
    ScheduleEntry,
    Booking,
    User,
    PublishedSchedule,
    AdminAction,
)
from src.models.models import Payment
from src.models.enums import TrainingType, AdminActionType, BookingStatus
from src.business_logic.schemas import (
    TrainingCreate,
    TrainingResponse,
    ScheduleEntryCreate,
)

logger = logging.getLogger(__name__)


class AdminService:
    """Service for administrative operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    # Training management
    def _check_time_conflict(self, day_of_week: int, start_time: str, duration_minutes: int, exclude_id: int = None):
        """Check if there's a time conflict with existing active trainings."""
        h, m = map(int, start_time.split(":"))
        new_start = h * 60 + m
        new_end = new_start + duration_minutes

        query = self.db.query(Training).filter(
            Training.day_of_week == day_of_week,
            Training.is_active == True,
        )
        if exclude_id:
            query = query.filter(Training.id != exclude_id)

        for t in query.all():
            th, tm = map(int, t.start_time.split(":"))
            existing_start = th * 60 + tm
            existing_end = existing_start + t.duration_minutes
            if new_start < existing_end and existing_start < new_end:
                end_time_str = f"{existing_end // 60:02d}:{existing_end % 60:02d}"
                raise ValueError(
                    f"Время занято: «{t.title}» ({t.start_time}–{end_time_str})"
                )

    def create_training(self, training_data: TrainingCreate, admin_id: int) -> Training:
        """Create a new training template."""
        data = training_data.dict()
        participant_ids = data.pop("participant_ids", None) or []

        self._check_time_conflict(data["day_of_week"], data["start_time"], data["duration_minutes"])

        training = Training(**data)
        self.db.add(training)
        self.db.flush()

        for uid in participant_ids:
            self.db.add(TrainingParticipant(training_id=training.id, user_id=uid))

        self.db.commit()
        self.db.refresh(training)

        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.CREATE_TRAINING,
            target_id=training.id,
            details=f"Created training: {training.title}"
        )

        return training

    def update_training(self, training_id: int, update_data: dict, admin_id: int) -> Training:
        """Update an existing training."""
        training = self.db.query(Training).filter(Training.id == training_id).first()
        if not training:
            raise ValueError(f"Training with id {training_id} not found")

        participant_ids = update_data.pop("participant_ids", None)

        day = update_data.get("day_of_week", training.day_of_week)
        start = update_data.get("start_time", training.start_time)
        dur = update_data.get("duration_minutes", training.duration_minutes)
        self._check_time_conflict(day, start, dur, exclude_id=training_id)

        for key, value in update_data.items():
            if hasattr(training, key):
                setattr(training, key, value)

        if participant_ids is not None:
            self.db.query(TrainingParticipant).filter(
                TrainingParticipant.training_id == training_id
            ).delete()
            for uid in participant_ids:
                self.db.add(TrainingParticipant(training_id=training_id, user_id=uid))

        training.updated_at = datetime.now()
        self.db.commit()
        self.db.refresh(training)

        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.UPDATE_TRAINING,
            target_id=training.id,
            details=f"Updated training: {training.title}"
        )

        return training

    def delete_training(self, training_id: int, admin_id: int) -> bool:
        """Hard delete a training and all related data."""
        training = self.db.query(Training).filter(Training.id == training_id).first()
        if not training:
            raise ValueError(f"Training with id {training_id} not found")

        title = training.title

        self.db.query(TrainingParticipant).filter(
            TrainingParticipant.training_id == training_id
        ).delete()
        self.db.query(Booking).filter(Booking.training_id == training_id).delete()
        self.db.query(ScheduleEntry).filter(ScheduleEntry.training_id == training_id).delete()
        self.db.delete(training)
        self.db.commit()

        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.DELETE_TRAINING,
            target_id=training_id,
            details=f"Deleted training: {title}"
        )

        return True
    
    def get_all_trainings(self, include_inactive: bool = False) -> List[Training]:
        """Get all training templates."""
        query = self.db.query(Training)
        if not include_inactive:
            query = query.filter(Training.is_active == True)
        return query.order_by(Training.day_of_week, Training.start_time).all()
    
    # Schedule management
    def create_schedule_entry(self, entry_data: ScheduleEntryCreate, admin_id: int) -> ScheduleEntry:
        """Create a specific schedule entry (one-time training)."""
        # Check if training exists
        training = self.db.query(Training).filter(Training.id == entry_data.training_id).first()
        if not training:
            raise ValueError(f"Training with id {entry_data.training_id} not found")
        
        entry = ScheduleEntry(**entry_data.dict())
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.CREATE_SCHEDULE_ENTRY,
            target_id=entry.id,
            details=f"Created schedule entry for {training.title} on {entry.date}"
        )
        
        return entry
    
    def update_schedule_entry(self, entry_id: int, update_data: dict, admin_id: int) -> ScheduleEntry:
        """Update a schedule entry."""
        entry = self.db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
        if not entry:
            raise ValueError(f"Schedule entry with id {entry_id} not found")
        
        for key, value in update_data.items():
            if hasattr(entry, key):
                setattr(entry, key, value)
        
        self.db.commit()
        self.db.refresh(entry)
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.UPDATE_SCHEDULE_ENTRY,
            target_id=entry.id,
            details=f"Updated schedule entry for {entry.training.title}"
        )
        
        return entry
    
    def cancel_schedule_entry(self, entry_id: int, reason: str, admin_id: int) -> ScheduleEntry:
        """Cancel a schedule entry."""
        entry = self.db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
        if not entry:
            raise ValueError(f"Schedule entry with id {entry_id} not found")
        
        entry.is_cancelled = True
        entry.cancellation_reason = reason
        self.db.commit()
        self.db.refresh(entry)
        
        # Notify users with bookings
        bookings = self.db.query(Booking).filter(
            Booking.schedule_entry_id == entry_id,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
        ).all()
        
        for booking in bookings:
            booking.status = BookingStatus.CANCELLED
        
        self.db.commit()
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.CANCEL_SCHEDULE_ENTRY,
            target_id=entry.id,
            details=f"Cancelled schedule entry: {reason}"
        )
        
        return entry
    
    # Booking management
    def get_pending_bookings(self) -> List[Booking]:
        """Get all active bookings (pending first, then confirmed)."""
        return (
            self.db.query(Booking)
            .filter(Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]))
            .order_by(
                (Booking.status == BookingStatus.PENDING).desc(),
                Booking.created_at.desc(),
            )
            .all()
        )
    
    def confirm_booking(self, booking_id: int, admin_id: int) -> Booking:
        """Confirm a booking."""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError(f"Booking with id {booking_id} not found")
        
        booking.status = BookingStatus.CONFIRMED
        self.db.commit()
        self.db.refresh(booking)
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.CONFIRM_BOOKING,
            target_id=booking.id,
            details=f"Confirmed booking for user {booking.user_id}"
        )
        
        return booking
    
    def reject_booking(self, booking_id: int, reason: str, admin_id: int) -> Booking:
        """Reject a booking."""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError(f"Booking with id {booking_id} not found")
        
        booking.status = BookingStatus.CANCELLED
        booking.notes = f"Rejected: {reason}"
        self.db.commit()
        self.db.refresh(booking)
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.REJECT_BOOKING,
            target_id=booking.id,
            details=f"Rejected booking: {reason}"
        )
        
        return booking
    
    # User management
    def get_all_users(self) -> List[User]:
        """Get all users."""
        return self.db.query(User).order_by(User.created_at.desc()).all()
    
    def update_user_admin_status(self, user_id: int, is_admin: bool, admin_id: int) -> User:
        """Update user's admin status."""
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError(f"User with id {user_id} not found")
        
        user.is_admin = is_admin
        self.db.commit()
        self.db.refresh(user)
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.UPDATE_USER_ADMIN_STATUS,
            target_id=user.id,
            details=f"Set admin status to {is_admin} for user {user.first_name}"
        )
        
        return user
    
    # Helper methods
    def _log_admin_action(self, admin_id: int, action_type: str, target_id: Optional[int] = None, details: Optional[str] = None):
        """Log an administrative action."""
        from src.models.models import User
        if not self.db.query(User).filter(User.id == admin_id).first():
            return
        action = AdminAction(
            admin_id=admin_id,
            action_type=action_type,
            target_id=target_id,
            details=details,
        )
        self.db.add(action)
        self.db.commit()
    
    def update_payment_status(self, booking_id: int, is_paid: bool, admin_id: int):
        """Отметить оплату для бронирования."""
        from datetime import datetime

        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError(f"Booking {booking_id} not found")

        payment = self.db.query(Payment).filter(Payment.booking_id == booking_id).first()
        if payment:
            payment.is_paid = is_paid
            payment.paid_at = datetime.now() if is_paid else None
        else:
            payment = Payment(
                booking_id=booking_id,
                user_id=booking.user_id,
                amount=0,
                is_paid=is_paid,
                paid_at=datetime.now() if is_paid else None,
            )
            self.db.add(payment)

        self.db.commit()
        return payment

    def get_user_by_telegram_id(self, telegram_id: int):
        """Найти пользователя по Telegram ID."""
        return self.db.query(User).filter(User.telegram_id == telegram_id).first()

    def search_users(self, query: str) -> List[User]:
        """Search users by name."""
        pattern = f"%{query}%"
        return (
            self.db.query(User)
            .filter(
                or_(
                    User.first_name.ilike(pattern),
                    User.last_name.ilike(pattern),
                    User.username.ilike(pattern),
                )
            )
            .limit(20)
            .all()
        )

    def create_quick_user(self, first_name: str, last_name: str = None) -> User:
        """Create a user with just a name (no messenger IDs yet)."""
        user = User(first_name=first_name, last_name=last_name)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_training_participants(self, training_id: int) -> List[dict]:
        """Get participants assigned to a training template."""
        participants = (
            self.db.query(TrainingParticipant)
            .filter(TrainingParticipant.training_id == training_id)
            .all()
        )
        result = []
        for p in participants:
            user = self.db.query(User).filter(User.id == p.user_id).first()
            if user:
                result.append({
                    "id": user.id,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                })
        return result

    def get_schedule_entry_details(self, entry_id: int) -> dict:
        """Get schedule entry with bookings, participants and payment info."""
        entry = self.db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
        if not entry:
            raise ValueError(f"Schedule entry {entry_id} not found")

        bookings = (
            self.db.query(Booking)
            .filter(
                Booking.schedule_entry_id == entry_id,
                Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
            )
            .all()
        )

        return {
            "id": entry.id,
            "training_id": entry.training_id,
            "title": entry.training.title,
            "training_type": entry.training.training_type.value,
            "date": entry.date.strftime("%Y-%m-%d"),
            "start_time": entry.start_time,
            "end_time": entry.end_time,
            "max_participants": entry.training.max_participants,
            "is_cancelled": entry.is_cancelled,
            "bookings": [
                {
                    "booking_id": b.id,
                    "user_id": b.user_id,
                    "user_name": f"{b.user.first_name} {b.user.last_name or ''}".strip(),
                    "status": b.status.value,
                    "is_paid": b.payment.is_paid if b.payment else False,
                }
                for b in bookings
            ],
        }

    def add_booking_for_entry(self, entry_id: int, user_id: int, admin_id: int) -> Booking:
        """Admin adds a participant to a schedule entry."""
        entry = self.db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
        if not entry:
            raise ValueError(f"Schedule entry {entry_id} not found")

        existing = (
            self.db.query(Booking)
            .filter(
                Booking.schedule_entry_id == entry_id,
                Booking.user_id == user_id,
                Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
            )
            .first()
        )
        if existing:
            raise ValueError("Пользователь уже записан на эту тренировку")

        booking = Booking(
            user_id=user_id,
            training_id=entry.training_id,
            schedule_entry_id=entry_id,
            status=BookingStatus.CONFIRMED,
        )
        self.db.add(booking)
        self.db.commit()
        self.db.refresh(booking)

        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.CONFIRM_BOOKING,
            target_id=booking.id,
            details=f"Admin added user {user_id} to entry {entry_id}",
        )
        return booking

    def delete_booking(self, booking_id: int, admin_id: int):
        """Delete a booking (remove participant)."""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError(f"Booking {booking_id} not found")

        self.db.query(Payment).filter(Payment.booking_id == booking_id).delete()
        self.db.delete(booking)
        self.db.commit()

        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.REJECT_BOOKING,
            target_id=booking_id,
            details=f"Admin deleted booking {booking_id}",
        )

    def delete_schedule_entry(self, entry_id: int, admin_id: int):
        """Hard delete a schedule entry and its bookings."""
        from src.models.models import Reminder
        entry = self.db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
        if not entry:
            raise ValueError(f"Schedule entry {entry_id} not found")

        booking_ids = [b.id for b in self.db.query(Booking.id).filter(Booking.schedule_entry_id == entry_id).all()]
        if booking_ids:
            self.db.query(Reminder).filter(Reminder.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            self.db.query(Payment).filter(Payment.booking_id.in_(booking_ids)).delete(synchronize_session=False)
            self.db.query(Booking).filter(Booking.id.in_(booking_ids)).delete(synchronize_session=False)

        title = entry.training.title
        self.db.delete(entry)
        self.db.commit()

        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.CANCEL_SCHEDULE_ENTRY,
            target_id=entry_id,
            details=f"Deleted schedule entry: {title}",
        )

    def get_admin_actions(self, limit: int = 100) -> List[AdminAction]:
        """Get recent admin actions."""
        return (
            self.db.query(AdminAction)
            .order_by(AdminAction.performed_at.desc())
            .limit(limit)
            .all()
        )