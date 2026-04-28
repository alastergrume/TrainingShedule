from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, date, time
from sqlalchemy.orm import Session
from sqlalchemy import and_
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

    def create_training(self, training_data: TrainingCreate) -> Training:
        training = Training(**training_data.dict())
        self.db.add(training)
        self.db.commit()
        self.db.refresh(training)
        return training

    def get_trainings_by_type(self, training_type: TrainingType) -> List[Training]:
        return (
            self.db.query(Training)
            .filter(Training.training_type == training_type, Training.is_active == True)
            .all()
        )

    def generate_weekly_schedule(
        self, week_start: date, include_basic: bool = True
    ) -> List[ScheduleEntry]:
        """Generate ScheduleEntry rows for a week from Training templates."""
        schedule_entries = []

        query = self.db.query(Training).filter(Training.is_active == True)
        if not include_basic:
            query = query.filter(Training.training_type != TrainingType.BASIC)

        trainings = query.all()

        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            day_of_week = current_date.weekday()

            for training in trainings:
                if training.day_of_week != day_of_week:
                    continue

                h, m = map(int, training.start_time.split(":"))
                start_dt = datetime.combine(current_date, time(h, m))
                end_dt = start_dt + timedelta(minutes=training.duration_minutes)

                existing = (
                    self.db.query(ScheduleEntry)
                    .filter(
                        ScheduleEntry.training_id == training.id,
                        ScheduleEntry.date == start_dt,
                    )
                    .first()
                )
                if existing:
                    continue

                entry = ScheduleEntry(
                    training_id=training.id,
                    date=start_dt,
                    start_time=training.start_time,
                    end_time=end_dt.strftime("%H:%M"),
                    is_cancelled=False,
                )
                self.db.add(entry)
                schedule_entries.append(entry)

        self.db.commit()
        return schedule_entries

    def get_week_schedule(
        self, week_start: date, include_basic: bool = True
    ) -> List[Dict[str, Any]]:
        """Return formatted schedule for a week, grouped by day."""
        week_start_dt = datetime.combine(week_start, time.min)
        week_end_dt = datetime.combine(week_start + timedelta(days=7), time.min)

        query = (
            self.db.query(ScheduleEntry)
            .join(Training)
            .filter(
                and_(
                    ScheduleEntry.date >= week_start_dt,
                    ScheduleEntry.date < week_end_dt,
                    ScheduleEntry.is_cancelled == False,
                )
            )
        )
        if not include_basic:
            query = query.filter(Training.training_type != TrainingType.BASIC)

        entries = query.order_by(ScheduleEntry.date, ScheduleEntry.start_time).all()

        schedule_by_day: Dict[str, list] = {}
        for entry in entries:
            day_key = entry.date.strftime("%Y-%m-%d")
            schedule_by_day.setdefault(day_key, []).append(entry)

        result = []
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            day_key = current_date.strftime("%Y-%m-%d")

            formatted_entries = []
            for entry in schedule_by_day.get(day_key, []):
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
                                "booking_id": b.id,
                                "user_id": b.user_id,
                                "user_name": self._get_user_name(b.user_id),
                                "status": b.status.value if hasattr(b.status, "value") else b.status,
                                "paid": b.payment.is_paid if b.payment else False,
                            }
                            for b in bookings
                        ],
                        "max_participants": entry.training.max_participants,
                        "is_full": bool(
                            entry.training.max_participants
                            and len(bookings) >= entry.training.max_participants
                        ),
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

    def _get_user_name(self, user_id: int) -> str:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            return "Unknown"
        return f"{user.first_name} {user.last_name or ''}".strip()

    def create_booking(self, booking_data: BookingCreate) -> Booking:
        training = (
            self.db.query(Training).filter(Training.id == booking_data.training_id).first()
        )
        if not training:
            raise ValueError("Training not found")

        if training.training_type == TrainingType.BASIC:
            raise ValueError(
                "Запись на базовые тренировки не доступна через бота. "
                "Обратитесь к администраторам фитнес-клуба."
            )

        # Check capacity per specific schedule entry (not the whole template)
        if training.max_participants and booking_data.schedule_entry_id:
            current_bookings = (
                self.db.query(Booking)
                .filter(
                    Booking.schedule_entry_id == booking_data.schedule_entry_id,
                    Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
                )
                .count()
            )
            if current_bookings >= training.max_participants:
                raise ValueError("Тренировка заполнена")

        booking = Booking(**booking_data.dict())
        self.db.add(booking)
        self.db.commit()
        self.db.refresh(booking)
        return booking

    def confirm_booking(self, booking_id: int, admin_id: int) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Booking not found")

        booking.status = BookingStatus.CONFIRMED
        self.db.commit()
        self.db.refresh(booking)
        return booking

    def cancel_booking(self, booking_id: int, reason: str = None) -> Booking:
        booking = self.db.query(Booking).filter(Booking.id == booking_id).first()
        if not booking:
            raise ValueError("Booking not found")

        booking.status = BookingStatus.CANCELLED
        if reason:
            booking.notes = reason
        self.db.commit()
        self.db.refresh(booking)
        return booking

    def publish_schedule(
        self,
        week_start: date,
        content: str,
        telegram_message_id: int = None,
        vk_post_id: int = None,
    ) -> PublishedSchedule:
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
        from_date = datetime.now()
        to_date = from_date + timedelta(days=days)

        bookings = (
            self.db.query(Booking)
            .join(ScheduleEntry)
            .filter(
                Booking.user_id == user_id,
                Booking.status == BookingStatus.CONFIRMED,
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
