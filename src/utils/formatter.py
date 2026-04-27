from typing import List, Dict, Any
from datetime import datetime, date, timedelta
import locale

# Set Russian locale for day names
try:
    locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')
except locale.Error:
    # Fallback to English if Russian locale not available
    pass


class ScheduleFormatter:
    """Format schedule data into human-readable messages."""
    
    @staticmethod
    def format_week_schedule(schedule_data: List[Dict], week_start: date) -> str:
        """Format weekly schedule according to the template from TZ.md."""
        lines = ["Расписание тренировок на следующую неделю:"]
        
        for day_data in schedule_data:
            day_date = day_data['date']
            day_name = day_data['day_name']
            
            # Format: "Понедельник 27.04:"
            formatted_date = day_date.strftime("%d.%m")
            lines.append(f"\n{day_name} {formatted_date}:")
            
            for entry in day_data['entries']:
                time = entry['time']
                title = entry['title']
                training_type = entry['type']
                
                # Determine suffix based on type
                if training_type == 'basic':
                    suffix = " (Базовая)"
                elif training_type == 'commercial':
                    suffix = "💸 (Коммерческая)"
                elif training_type == 'personal':
                    suffix = f" (Персональная тренировка {title})"
                    title = ""  # Title already contains name
                else:
                    suffix = ""
                
                line = f"{time}- {title}{suffix}"
                
                # Add participants for commercial trainings
                if training_type == 'commercial' and entry.get('bookings'):
                    for booking in entry['bookings']:
                        user_name = booking.get('user_name', '')
                        paid = booking.get('paid', False)
                        line += f"\n    - {user_name}"
                        if paid:
                            line += " ✅"
                
                lines.append(line)
        
        # Add footer
        lines.append("\n💸-коммерческая группа. Оплата 400₽ наличными или он-лайн переводом на карту Т-банк или сбер по номеру телефона <номер телефона> <ФИО Администратора>")
        lines.append("Занимайте свободные места.❤️")
        lines.append("Персональные тренировки тоже будут подписаны именами, можно будет свериться. Если не подписана именем-значит свободна.")
        lines.append("Так же по сплит-тренировкам.")
        
        return "\n".join(lines)
    
    @staticmethod
    def format_reminder(booking_data: Dict) -> str:
        """Format reminder message for a booking."""
        training = booking_data.get('training', {})
        schedule = booking_data.get('schedule', {})
        
        return (
            f"Напоминание о тренировке!\n"
            f"Тренировка: {training.get('title', 'Неизвестно')}\n"
            f"Дата и время: {schedule.get('date', '')} {schedule.get('time', '')}\n"
            f"Место: спортивный зал\n\n"
            f"Пожалуйста, подтвердите, что придете, ответив 'Да' или 'Нет'."
        )
    
    @staticmethod
    def format_booking_confirmation(booking_data: Dict) -> str:
        """Format booking confirmation message."""
        return (
            f"Ваша запись подтверждена!\n"
            f"Тренировка: {booking_data.get('training_title')}\n"
            f"Дата: {booking_data.get('date')}\n"
            f"Время: {booking_data.get('time')}\n"
            f"Статус: {booking_data.get('status')}"
        )
    
    @staticmethod
    def format_admin_notification(action: str, data: Dict) -> str:
        """Format notification for administrators."""
        if action == "new_booking":
            return (
                f"Новая запись на тренировку!\n"
                f"Пользователь: {data.get('user_name')}\n"
                f"Тренировка: {data.get('training_title')}\n"
                f"Время: {data.get('time')}\n"
                f"Требует подтверждения."
            )
        elif action == "schedule_published":
            return f"Расписание на неделю {data.get('week_start')} опубликовано."
        else:
            return f"Административное уведомление: {action}"


class ScheduleGenerator:
    """Generate schedule data from database models."""
    
    @staticmethod
    def generate_from_db(db_session, week_start: date) -> List[Dict]:
        """Generate schedule from database for a given week."""
        from src.models import Training, ScheduleEntry
        from sqlalchemy import and_
        
        week_end = week_start + timedelta(days=6)
        
        # Get schedule entries for the week
        entries = (
            db_session.query(ScheduleEntry)
            .join(Training)
            .filter(
                and_(
                    ScheduleEntry.date >= week_start,
                    ScheduleEntry.date <= week_end,
                    ScheduleEntry.is_cancelled == False,
                )
            )
            .order_by(ScheduleEntry.date, ScheduleEntry.start_time)
            .all()
        )
        
        # Group by day
        schedule_by_day = {}
        for entry in entries:
            day_key = entry.date.strftime("%Y-%m-%d")
            if day_key not in schedule_by_day:
                schedule_by_day[day_key] = []
            
            # Get bookings for this entry
            from src.models import Booking, User
            bookings = (
                db_session.query(Booking)
                .join(User)
                .filter(
                    Booking.schedule_entry_id == entry.id,
                    Booking.status.in_(["confirmed", "pending"]),
                )
                .all()
            )
            
            schedule_by_day[day_key].append({
                "time": f"{entry.start_time}-{entry.end_time}",
                "title": entry.training.title,
                "type": entry.training.training_type.value,
                "bookings": [
                    {
                        "user_name": f"{booking.user.first_name} {booking.user.last_name or ''}".strip(),
                        "paid": any(p.is_paid for p in booking.user.payments if p.booking_id == booking.id),
                    }
                    for booking in bookings
                ],
            })
        
        # Convert to list of days
        result = []
        for day_offset in range(7):
            current_date = week_start + timedelta(days=day_offset)
            day_key = current_date.strftime("%Y-%m-%d")
            
            result.append({
                "date": current_date,
                "day_name": current_date.strftime("%A"),
                "entries": schedule_by_day.get(day_key, []),
            })
        
        return result