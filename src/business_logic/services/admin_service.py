from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, update
import logging

from src.models import (
    Training,
    ScheduleEntry,
    Booking,
    User,
    PublishedSchedule,
    AdminAction,
)
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
    def create_training(self, training_data: TrainingCreate, admin_id: int) -> Training:
        """Create a new training template."""
        training = Training(**training_data.dict())
        self.db.add(training)
        self.db.commit()
        self.db.refresh(training)
        
        # Log admin action
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
        
        for key, value in update_data.items():
            if hasattr(training, key):
                setattr(training, key, value)
        
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
        """Soft delete a training (set is_active=False)."""
        training = self.db.query(Training).filter(Training.id == training_id).first()
        if not training:
            raise ValueError(f"Training with id {training_id} not found")
        
        training.is_active = False
        training.updated_at = datetime.now()
        self.db.commit()
        
        self._log_admin_action(
            admin_id=admin_id,
            action_type=AdminActionType.DELETE_TRAINING,
            target_id=training.id,
            details=f"Deleted training: {training.title}"
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
            Booking.status.in_(["confirmed", "pending"])
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
        """Get all pending bookings requiring admin approval."""
        return (
            self.db.query(Booking)
            .filter(Booking.status == "pending")
            .order_by(Booking.created_at)
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
        action = AdminAction(
            admin_id=admin_id,
            action_type=action_type,
            target_id=target_id,
            details=details,
        )
        self.db.add(action)
        self.db.commit()
    
    def get_admin_actions(self, limit: int = 100) -> List[AdminAction]:
        """Get recent admin actions."""
        return (
            self.db.query(AdminAction)
            .order_by(AdminAction.performed_at.desc())
            .limit(limit)
            .all()
        )