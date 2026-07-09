from typing import List, Dict, Any
from datetime import datetime, date, timedelta

# Русские названия дней недели (weekday() → 0=пн, 6=вс)
_RU_DAY_NAMES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}


def _ru_day_name(d: date) -> str:
    return _RU_DAY_NAMES[d.weekday()]


class ScheduleFormatter:
    """Форматирует данные расписания в текстовые сообщения."""

    @staticmethod
    def format_week_schedule(schedule_data: List[Dict], week_start: date) -> str:
        """
        Форматирует недельное расписание по шаблону из ТЗ.

        schedule_data — список dict с ключами:
            date: date, entries: list[{time, title, type, bookings: [{user_name, paid}]}]
        """
        week_end = week_start + timedelta(days=6)
        lines = [
            f"Расписание тренировок на неделю "
            f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m')}:"
        ]

        for day_data in schedule_data:
            day_date = day_data.get('date')
            if isinstance(day_date, datetime):
                day_date = day_date.date()
            elif isinstance(day_date, str):
                day_date = date.fromisoformat(day_date[:10])

            if not day_date or not day_data.get('entries'):
                continue

            day_name = _ru_day_name(day_date)
            formatted_date = day_date.strftime("%d.%m")
            lines.append(f"\n{day_name} {formatted_date}:")

            for entry in day_data['entries']:
                start_time = entry['time'].split('-')[0]  # "09:00-10:00" → "09:00"
                title = entry['title']
                training_type = entry['type']

                if training_type == 'basic':
                    line = f"{start_time}- {title} (Базовая)"

                elif training_type == 'commercial':
                    line = f"{start_time}- {title}💸 (Коммерческая)"
                    for booking in entry.get('bookings', []):
                        user_name = booking.get('user_name', '')
                        paid = booking.get('paid', False)
                        paid_mark = " ✅" if paid else ""
                        line += f"\n    - {user_name}{paid_mark}"
                    # Пустые строки для свободных мест
                    max_p = entry.get('max_participants')
                    filled = len(entry.get('bookings', []))
                    if max_p and filled < max_p:
                        for _ in range(max_p - filled):
                            line += "\n    -"

                else:  # personal
                    bookings = entry.get('bookings', [])
                    if bookings:
                        participant = bookings[0].get('user_name', '')
                        line = f"{start_time}- {title} ({participant})"
                    else:
                        line = f"{start_time}- {title} (свободна)"

                lines.append(line)

        lines.append(
            "\n💸-коммерческая группа. Оплата 400₽ наличными или он-лайн переводом "
            "на карту Т-банк или сбер по номеру телефона <номер телефона> <ФИО Администратора>"
        )
        lines.append("Занимайте свободные места.❤️")
        lines.append(
            "Персональные тренировки тоже будут подписаны именами, можно будет свериться. "
            "Если не подписана именем-значит свободна."
        )
        lines.append("Так же по сплит-тренировкам.")

        return "\n".join(lines)

    @staticmethod
    def format_reminder(booking_data: Dict) -> str:
        training = booking_data.get('training', {})
        schedule = booking_data.get('schedule', {})
        return (
            f"Напоминание о тренировке!\n"
            f"Тренировка: {training.get('title', 'Неизвестно')}\n"
            f"Дата и время: {schedule.get('date', '')} {schedule.get('time', '')}\n"
            f"Место: спортивный зал\n\n"
            f"Пожалуйста, подтвердите, что придёте, ответив 'Да' или 'Нет'."
        )

    @staticmethod
    def format_booking_confirmation(booking_data: Dict) -> str:
        return (
            f"Ваша запись подтверждена!\n"
            f"Тренировка: {booking_data.get('training_title')}\n"
            f"Дата: {booking_data.get('date')}\n"
            f"Время: {booking_data.get('time')}\n"
            f"Статус: Подтверждено"
        )

    @staticmethod
    def format_admin_notification(action: str, data: Dict) -> str:
        if action == "new_booking":
            return (
                f"Новая заявка на тренировку!\n"
                f"Пользователь: {data.get('user_name')}\n"
                f"Тренировка: {data.get('training_title')}\n"
                f"Время: {data.get('time')}\n"
                f"Требует подтверждения."
            )
        elif action == "schedule_generated":
            return (
                f"Расписание на неделю {data.get('week_start')} сгенерировано. "
                f"Создано записей: {data.get('entries_count')}."
            )
        elif action == "schedule_published":
            return f"Расписание на неделю {data.get('week_start')} опубликовано."
        else:
            return f"Административное уведомление: {action}"


class ScheduleGenerator:
    """Генерирует данные расписания из базы данных."""

    @staticmethod
    def generate_from_db(db_session, week_start: date) -> List[Dict]:
        from src.models.models import Training, ScheduleEntry, Booking, User
        from src.models.enums import BookingStatus
        from sqlalchemy import and_
        from datetime import time

        week_start_dt = datetime.combine(week_start, time.min)
        week_end_dt = datetime.combine(week_start + timedelta(days=7), time.min)

        entries = (
            db_session.query(ScheduleEntry)
            .join(Training)
            .filter(
                and_(
                    ScheduleEntry.date >= week_start_dt,
                    ScheduleEntry.date < week_end_dt,
                    ScheduleEntry.is_cancelled == False,
                )
            )
            .order_by(ScheduleEntry.date, ScheduleEntry.start_time)
            .all()
        )

        schedule_by_day: Dict[str, list] = {}
        for entry in entries:
            day_key = entry.date.strftime("%Y-%m-%d")
            schedule_by_day.setdefault(day_key, [])

            bookings = (
                db_session.query(Booking)
                .join(User)
                .filter(
                    Booking.schedule_entry_id == entry.id,
                    Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.PENDING]),
                )
                .all()
            )

            schedule_by_day[day_key].append({
                "id": entry.id,
                "time": f"{entry.start_time}-{entry.end_time}",
                "title": entry.training.title,
                "type": entry.training.training_type.value,
                "max_participants": entry.training.max_participants,
                "is_cancelled": entry.is_cancelled,
                "bookings": [
                    {
                        "booking_id": b.id,
                        "user_name": f"{b.user.first_name} {b.user.last_name or ''}".strip(),
                        "paid": any(
                            p.is_paid for p in b.user.payments if p.booking_id == b.id
                        ),
                    }
                    for b in bookings
                ],
            })

        result = []
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            day_key = current_date.strftime("%Y-%m-%d")
            result.append({
                "date": current_date,
                "day_name": _ru_day_name(current_date),
                "entries": schedule_by_day.get(day_key, []),
            })

        return result
