from celery import Celery
from celery.schedules import crontab
from datetime import datetime, timedelta
import logging
from sqlalchemy.orm import Session

from src.config import settings
from src.models import get_db, Booking, ScheduleEntry, Reminder, User, Training
from src.messengers.interfaces.messenger import MessengerFactory
from src.utils.formatter import ScheduleFormatter, ScheduleGenerator

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    'training_schedule',
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=['src.celery_app']
)

# Configure Celery
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Europe/Moscow',
    enable_utc=True,
    beat_schedule={
        # Generate weekly schedule every Sunday at 18:00
        'generate-weekly-schedule': {
            'task': 'src.celery_app.generate_weekly_schedule',
            'schedule': crontab(hour=18, minute=0, day_of_week=0),  # Sunday
        },
        # Send reminders 60 minutes before each training
        'send-reminders': {
            'task': 'src.celery_app.send_upcoming_reminders',
            'schedule': crontab(minute='*/5'),  # Every 5 minutes
        },
        # Cleanup old data
        'cleanup-old-data': {
            'task': 'src.celery_app.cleanup_old_data',
            'schedule': crontab(hour=3, minute=0),  # Daily at 3 AM
        },
    }
)


@celery_app.task
def generate_weekly_schedule():
    """Generate schedule for the upcoming week."""
    from src.business_logic.services.schedule_service import ScheduleService
    
    try:
        with next(get_db()) as db:
            service = ScheduleService(db)
            # Calculate next week start (Monday)
            today = datetime.now().date()
            days_ahead = 7 - today.weekday()  # Monday is 0
            if days_ahead <= 0:  # Today is Monday or later in week
                days_ahead += 7
            week_start = today + timedelta(days=days_ahead)
            
            # Generate schedule entries
            entries = service.generate_weekly_schedule(week_start)
            
            logger.info(f"Generated {len(entries)} schedule entries for week starting {week_start}")
            
            # Notify admins
            if settings.ADMIN_NOTIFICATION_ENABLED:
                notify_admins.delay(
                    "schedule_generated",
                    {"week_start": week_start.isoformat(), "entries_count": len(entries)}
                )
            
            return {"status": "success", "entries_count": len(entries), "week_start": week_start.isoformat()}
    except Exception as e:
        logger.error(f"Failed to generate weekly schedule: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def send_upcoming_reminders():
    """Send reminders for trainings starting soon."""
    try:
        with next(get_db()) as db:
            reminder_minutes = settings.REMINDER_MINUTES_BEFORE
            reminder_time = datetime.now() + timedelta(minutes=reminder_minutes)
            
            # Find bookings that start within the reminder window
            bookings = (
                db.query(Booking)
                .join(ScheduleEntry)
                .filter(
                    Booking.status == 'confirmed',
                    ScheduleEntry.is_cancelled == False,
                    ScheduleEntry.date >= datetime.now(),
                    ScheduleEntry.date <= reminder_time,
                )
                .all()
            )
            
            sent_count = 0
            for booking in bookings:
                # Check if reminder already sent
                existing = (
                    db.query(Reminder)
                    .filter(
                        Reminder.booking_id == booking.id,
                        Reminder.sent_at.isnot(None),
                    )
                    .first()
                )
                
                if existing:
                    continue
                
                # Get user and training info
                user = db.query(User).filter(User.id == booking.user_id).first()
                training = booking.training
                schedule = booking.schedule_entry
                
                if not user or not training or not schedule:
                    continue
                
                # Determine which messengers to use
                messengers = []
                if user.telegram_id:
                    messengers.append('telegram')
                if user.vk_id:
                    messengers.append('vk')
                
                # Prepare reminder data
                reminder_data = {
                    'training': {
                        'title': training.title,
                        'type': training.training_type.value,
                    },
                    'schedule': {
                        'date': schedule.date.strftime("%d.%m.%Y"),
                        'time': schedule.start_time,
                    },
                    'user': {
                        'id': user.id,
                        'name': user.first_name,
                    }
                }
                
                # Send via each messenger
                for messenger_name in messengers:
                    try:
                        messenger = MessengerFactory.create(messenger_name)
                        user_id = str(user.telegram_id if messenger_name == 'telegram' else user.vk_id)
                        
                        # In real implementation, this would be async
                        # For Celery task, we'd need async handling
                        logger.info(f"Sending reminder to {user_id} via {messenger_name}")
                        
                        # Create reminder record
                        reminder = Reminder(
                            booking_id=booking.id,
                            reminder_time=datetime.now(),
                            channel=messenger_name,
                            sent_at=datetime.now(),
                        )
                        db.add(reminder)
                        sent_count += 1
                    except Exception as e:
                        logger.error(f"Failed to send reminder via {messenger_name}: {e}")
                
                db.commit()
            
            logger.info(f"Sent {sent_count} reminders")
            return {"status": "success", "reminders_sent": sent_count}
    except Exception as e:
        logger.error(f"Failed to send reminders: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def notify_admins(action: str, data: dict):
    """Send notification to administrators."""
    try:
        with next(get_db()) as db:
            admins = db.query(User).filter(User.is_admin == True).all()
            
            formatter = ScheduleFormatter()
            message = formatter.format_admin_notification(action, data)
            
            for admin in admins:
                # Send via Telegram if available
                if admin.telegram_id:
                    try:
                        messenger = MessengerFactory.create('telegram')
                        # In real implementation, use async
                        logger.info(f"Notifying admin {admin.id} via Telegram")
                    except Exception as e:
                        logger.error(f"Failed to notify admin {admin.id}: {e}")
                
                # Send via VK if available
                if admin.vk_id:
                    try:
                        messenger = MessengerFactory.create('vk')
                        logger.info(f"Notifying admin {admin.id} via VK")
                    except Exception as e:
                        logger.error(f"Failed to notify admin {admin.id}: {e}")
            
            return {"status": "success", "admins_notified": len(admins)}
    except Exception as e:
        logger.error(f"Failed to notify admins: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def cleanup_old_data(days_to_keep: int = 30):
    """Cleanup old data from database."""
    try:
        with next(get_db()) as db:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            
            # Cleanup old reminders
            deleted_reminders = (
                db.query(Reminder)
                .filter(Reminder.created_at < cutoff_date)
                .delete()
            )
            
            # Cleanup old schedule entries (keep some history)
            deleted_entries = (
                db.query(ScheduleEntry)
                .filter(
                    ScheduleEntry.date < cutoff_date,
                    ScheduleEntry.is_cancelled == False,
                )
                .delete()
            )
            
            db.commit()
            
            logger.info(f"Cleaned up {deleted_reminders} reminders and {deleted_entries} schedule entries")
            return {
                "status": "success",
                "deleted_reminders": deleted_reminders,
                "deleted_entries": deleted_entries,
            }
    except Exception as e:
        logger.error(f"Failed to cleanup old data: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def publish_schedule_to_channels(week_start: str, schedule_data: dict):
    """Publish schedule to all configured channels."""
    try:
        formatted_text = ScheduleFormatter.format_week_schedule(
            schedule_data['days'], 
            datetime.fromisoformat(week_start).date()
        )
        
        results = []
        
        # Publish to Telegram
        if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHANNEL_ID:
            try:
                telegram = MessengerFactory.create('telegram')
                result = telegram.send_schedule(
                    schedule_data,
                    parse_mode='HTML'
                )
                results.append({'channel': 'telegram', 'result': result})
            except Exception as e:
                logger.error(f"Failed to publish to Telegram: {e}")
                results.append({'channel': 'telegram', 'error': str(e)})
        
        # Publish to VK
        if settings.VK_GROUP_TOKEN and settings.VK_GROUP_ID:
            try:
                vk = MessengerFactory.create('vk')
                result = vk.send_schedule(schedule_data)
                results.append({'channel': 'vk', 'result': result})
            except Exception as e:
                logger.error(f"Failed to publish to VK: {e}")
                results.append({'channel': 'vk', 'error': str(e)})
        
        return {"status": "success", "results": results}
    except Exception as e:
        logger.error(f"Failed to publish schedule: {e}")
        return {"status": "error", "error": str(e)}