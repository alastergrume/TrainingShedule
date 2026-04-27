from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import logging

from src.models import (
    Training,
    ScheduleEntry,
    Booking,
    User,
    PublishedSchedule,
)
from src.models.enums import TrainingType, BookingStatus
from src.business_logic.schemas import (
    TrainingCreate,
    ScheduleEntryCreate,
    BookingCreate,
    WeekScheduleRequest,
)

logger = logging.getLogger(__name__)


class ScheduleService:
    def __init__(self, db: Session):
        self.db = db

    # Training management
    def create_training(self, training_data: TrainingCreate) -> Training:
        """Create a new training template."""
        training = Training(**training_data.dict())
        self.db.add(training)
        self.db.commit()
        self.db.refresh(training)
        return training

    def get_trainings_by_type(self, training_type: TrainingType) -> List[Training]:
        """Get all trainings of a specific type."""
        return (
            self.db.query(Training)
            .filter(Training.training_type == training_type, Training.is_active == True)
            .all()
        )

    def generate_weekly_schedule(
        self, week_start: date, include_basic: bool = True
    ) -> List[ScheduleEntry]:
        """Generate schedule entries for a week based on training templates."""
        week_end = week_start + timedelta(days=6)
        schedule_entries = []

        # Get all active trainings
        query = self.db.query(Training).filter(Training.is_active == True)
        if not include_basic:
            query = query.filter(Training.training_type != TrainingType.BASIC)

        trainings = query.all()

        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            day_of_week = current_date.weekday()  # Monday=0

            day_trainings = [t for t in trainings if t.day_of_week == day_of_week]

            for training in day_trainings:
                # Calculate start datetime
                start_time_parts = training.start_time.split(":")
                start_datetime = datetime.combine(
                    current_date,
                    datetime.min.time().replace(
                        hour=int(start_time_parts[0]), minute=int(start_time_parts[1])
                    ),
                )

                # Calculate end datetime
                end_datetime = start_datetime + timedelta(
                    minutes=training.duration_minutes
                )

                # Check if schedule entry already exists
                existing = (
                    self.db.query(ScheduleEntry)
                    .filter(
                        ScheduleEntry.training_id == training.id,
                        ScheduleEntry.date == start_datetime,
                    )
                    .first()
                )

                if not existing:
                    schedule_entry = ScheduleEntry(
                        training_id=training.id,
                        date=start_datetime,
                        start_time=training.start_time,
                        end_time=end_datetime.strftime("%H:%M"),
                        is_cancelled=False,
                    )
                    self.db.add(schedule_entry)
                    schedule_entries.append(schedule_entry)

        self.db.commit()
        return schedule_entries

    def get_week_schedule(
        self, week_start: date, include_basic: bool = True
    ) -> List[Dict[str, Any]]:
        """Get formatted schedule for a week."""
        week_end = week_start + timedelta(days=6)

        query = self.db.query(ScheduleEntry).join(Training).filter(
            and_(
                ScheduleEntry.date >= week_start,
                ScheduleEntry.date <= week_end,
                ScheduleEntry.is_cancelled == False,
            )
        )

        if not include_basic:
            query = query.filter(Training.training_type != TrainingType.BASIC)

        entries = query.order_by(ScheduleEntry.date, ScheduleEntry.start_time).all()

        # Group by day
        schedule_by_day = {}
        for entry in entries:
            day_key = entry.date.strftime("%Y-%m-%d")
            if day_key not in schedule_by_day:
                schedule_by_day[day_key] = []
            schedule_by_day[day_key].append(entry)

        result = []
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            day_key = current_date.strftime("%Y-%m-%d")
            day_entries = schedule_by_day.get(day_key, [])

            # Format each entry
            formatted_entries = []
            for entry in day_entries:
                bookings = (
                    self.db.query(Booking)
                    .filter(
                        Booking.schedule_entry_id == entry.id,
                        Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
                    )
                    .all()
                )

                formatted_entries.append(
                    {
                        "id": entry.id,
                        "time": f"{entry.start_time}-{entry.end_time}",
                        "title": entry.training.title,
                        "type": entry.training.training_type.value,
                        "bookings": [
                            {
                                "user_id": b.user_id,
                                "user_name": self.db.query(User)
                                .filter(User.id == b.user_id)
                                .first()
                                .first_name,
                                "status": b.status,
                            }
                            for b in bookings
                        ],
                        "max_participants": entry.training.max_participants,
                        "is_full": entry.training.max_participants
                        and len(bookings) >= entry.training.max_participants,
                    }
                )

            result.append(
                {
                    "date": current_date,
                    "day_name": current_date.strftime("%A"),
                    "entries": formatted_entries,
                }
            )

        return result

    def create_booking(self, booking_data: BookingCreate) -> Booking:
        """Create a booking for a training."""
        # Check if training exists and is bookable
        training = (
            self.db.query(Training).filter(Training.id == booking_data.training_id).first()
        )
        if not training:
            raise ValueError("Training not found")

        if training.training_type == TrainingType.BASIC:
            raise ValueError("Booking not allowed for basic trainings")

        # Check capacity
        if training.max_participants:
            current_bookings = (
                self.db.query(Booking)
                .filter(
                    Booking.training_id == training.id,
                    Booking.status.in_(["confirmed", "pending"]),
                )
                .count()
            )
            if current_bookings >= training.max_participants:
                raise ValueError("Training is full")

        booking = Booking(**booking_data.dict())
        self.db.add(booking)
        self.db.commit()
        self.db.refresh(booking)
        return booking

    def confirm_booking(self, booking_id: int, admin_id: int) -> Booking:
        """Confirm a booking by admin."""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Booking not found")

        booking.status = BookingStatus.CONFIRMED
        self.db.commit()
        self.db.refresh(booking)
        return booking

    def cancel_booking(self, booking_id: int, reason: str = None) -> Booking:
        """Cancel a booking."""
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Booking not found")

        booking.status = BookingStatus.CANCELLED
        self.db.commit()
        self.db.refresh(booking)
        return booking

    def publish_schedule(
        self, week_start: date, content: str, telegram_message_id: int = None, vk_post_id: int = None
    ) -> PublishedSchedule:
        """Publish schedule to social networks."""
        week_end = week_start + timedelta(days=6)

        published = PublishedSchedule(
            week_start_date=week_start,
            week_end_date=week_end,
            telegram_message_id=telegram_message_id,
            vk_post_id=vk_post_id,
            content=content,
        )
        self.db.add(published)
        self.db.commit()
        self.db.refresh(published)
        return published

    def get_upcoming_trainings(self, user_id: int, days: int = 7) -> List[Dict]:
        """Get upcoming trainings for a user."""
        from_date = datetime.now()
        to_date = from_date + timedelta(days=days)

        bookings = (
            self.db.query(Booking)
            .join(ScheduleEntry)
            .filter(
                Booking.user_id == user_id,
                Booking.status == "confirmed",
                ScheduleEntry.date >= from_date,
                ScheduleEntry.date <= to_date,
                ScheduleEntry.is_cancelled == False,
            )
            .all()
        )

        result = []
        for booking in bookings:
            result.append(
                {
                    "booking_id": booking.id,
                    "training_title": booking.training.title,
                    "date": booking.schedule_entry.date,
                    "time": booking.schedule_entry.start_time,
                    "type": booking.training.training_type.value,
                }
            )

        return result