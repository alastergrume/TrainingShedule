import sys
import asyncio
import sys
from celery import Celery
from celery.schedules import crontab
from datetime import datetime, timedelta
import logging

from src.config import settings
from pathlib import Path
from src.models.base import SessionLocal
from src.models.models import Booking, ScheduleEntry, Reminder, User
from src.utils.formatter import ScheduleFormatter

# # Register messengers so MessengerFactory knows about them
# if settings.TELEGRAM_BOT_TOKEN:
#     from src.messengers.telegram.bot import TelegramBot  # noqa: registers 'telegram'
# if settings.VK_GROUP_TOKEN:
#     from src.messengers.vk.bot import VKBot  # noqa: registers 'vk'

logger = logging.getLogger(__name__)

schedule_dir = Path(__file__).parent.parent.parent / "logs"
schedule_dir.mkdir(parents=True, exist_ok=True)

celery_app = Celery(
    'training_schedule',
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=['src.celery_app'],
)

celery_app.conf.update(
    result_expires=120,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    task_serializer='json',
    accept_content=['json'],
    broker_connection_retry_on_startup=True,
    result_serializer='json',
    timezone='Europe/Moscow',
    enable_utc=True,
    beat_schedule={
        'generate-weekly-schedule': {
            'task': 'src.celery_app.generate_weekly_schedule',
            'schedule': crontab(hour=18, minute=0, day_of_week=0),  # воскресенье
        },
        'send-reminders': {
            'task': 'src.celery_app.send_upcoming_reminders',
            'schedule': crontab(minute='*/5'),
        },
        'cleanup-old-data': {
            'task': 'src.celery_app.cleanup_old_data',
            'schedule': crontab(hour=3, minute=0),
        },
    },
)

# prefork (по умолчанию) не работает на Windows — billiard падает с PermissionError
if sys.platform == 'win32':
    celery_app.conf.worker_pool = 'solo'

# Регистрация мессенджеров в MessengerFactory (Celery не импортирует bot.py сам)
import src.messengers.telegram.bot  # noqa: F401
import src.messengers.vk.bot  # noqa: F401


@celery_app.task
def generate_weekly_schedule():
    """Генерирует расписание на следующую неделю из шаблонов тренировок."""
    from src.business_logic.services.schedule_service import ScheduleService

    db = SessionLocal()
    try:
        service = ScheduleService(db)
        today = datetime.now().date()
        days_ahead = 7 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        week_start = today + timedelta(days=days_ahead)

        entries = service.generate_weekly_schedule(week_start)
        logger.info(f"Generated {len(entries)} schedule entries for week {week_start}")

        if settings.ADMIN_NOTIFICATION_ENABLED:
            notify_admins.delay(
                "schedule_generated",
                {"week_start": week_start.isoformat(), "entries_count": len(entries)},
            )

        return {"status": "success", "entries_count": len(entries), "week_start": week_start.isoformat()}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to generate weekly schedule: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@celery_app.task
def send_upcoming_reminders():
    """Отправляет напоминания за REMINDER_MINUTES_BEFORE минут до тренировки."""
    db = SessionLocal()
    try:
        reminder_minutes = settings.REMINDER_MINUTES_BEFORE
        now = datetime.now()
        reminder_time = now + timedelta(minutes=reminder_minutes)

        from src.models.enums import BookingStatus
        bookings = (
            db.query(Booking)
            .join(ScheduleEntry)
            .filter(
                Booking.status == BookingStatus.CONFIRMED,
                ScheduleEntry.is_cancelled == False,
                ScheduleEntry.date >= now,
                ScheduleEntry.date <= reminder_time,
            )
            .all()
        )

        sent_count = 0
        for booking in bookings:
            already_sent = (
                db.query(Reminder)
                .filter(
                    Reminder.booking_id == booking.id,
                    Reminder.sent_at.isnot(None),
                )
                .first()
            )
            if already_sent:
                continue

            user = db.query(User).filter(User.id == booking.user_id).first()
            training = booking.training
            schedule = booking.schedule_entry

            if not user or not training or not schedule:
                continue

            reminder_data = {
                'training': {'title': training.title, 'type': training.training_type.value},
                'schedule': {
                    'date': schedule.date.strftime("%d.%m.%Y"),
                    'time': schedule.start_time,
                },
                'user': {'id': user.id, 'name': user.first_name},
            }

            if user.telegram_id:
                _send_reminder_via_messenger('telegram', str(user.telegram_id), reminder_data, booking.id, db)
                sent_count += 1
            if user.vk_id:
                _send_reminder_via_messenger('vk', str(user.vk_id), reminder_data, booking.id, db)
                sent_count += 1

        db.commit()
        logger.info(f"Sent {sent_count} reminders")
        return {"status": "success", "reminders_sent": sent_count}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to send reminders: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def _send_reminder_via_messenger(messenger_name: str, user_id: str, reminder_data: dict, booking_id: int, db):
    """Отправляет напоминание через мессенджер и сохраняет запись в БД."""
    from src.messengers.interfaces.messenger import MessengerFactory
    try:
        messenger = MessengerFactory.create(messenger_name)
        asyncio.run(messenger.send_reminder(user_id, reminder_data))

        reminder = Reminder(
            booking_id=booking_id,
            reminder_time=datetime.now(),
            channel=messenger_name,
            sent_at=datetime.now(),
        )
        db.add(reminder)
    except Exception as e:
        logger.error(f"Failed to send reminder via {messenger_name} to {user_id}: {e}")


@celery_app.task
def notify_admins(action: str, data: dict):
    """Уведомляет всех администраторов о событии."""
    from src.messengers.interfaces.messenger import MessengerFactory

    db = SessionLocal()
    try:
        admins = db.query(User).filter(User.is_admin == True).all()
        message = ScheduleFormatter.format_admin_notification(action, data)

        for admin in admins:
            if admin.telegram_id:
                try:
                    messenger = MessengerFactory.create('telegram')
                    asyncio.run(messenger.send_message(str(admin.telegram_id), message))
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin.id} via Telegram: {e}")

            if admin.vk_id:
                try:
                    messenger = MessengerFactory.create('vk')
                    asyncio.run(messenger.send_message(str(admin.vk_id), message))
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin.id} via VK: {e}")

        return {"status": "success", "admins_notified": len(admins)}
    except Exception as e:
        logger.error(f"Failed to notify admins: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


@celery_app.task
def cleanup_old_data(days_to_keep: int = 30):
    """Удаляет устаревшие напоминания и записи расписания."""
    db = SessionLocal()
    try:
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)

        deleted_reminders = (
            db.query(Reminder).filter(Reminder.created_at < cutoff_date).delete()
        )
        deleted_entries = (
            db.query(ScheduleEntry)
            .filter(
                ScheduleEntry.date < cutoff_date,
                ScheduleEntry.is_cancelled == False,
            )
            .delete()
        )
        db.commit()

        logger.info(f"Cleaned up {deleted_reminders} reminders, {deleted_entries} schedule entries")
        return {
            "status": "success",
            "deleted_reminders": deleted_reminders,
            "deleted_entries": deleted_entries,
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cleanup old data: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


async def _publish_all(schedule_data: dict,
                       telegram_message_id: int = None,
                       vk_post_id: int = None):
    """Single coroutine for all messenger publishing (one event loop)."""
    from src.messengers.interfaces.messenger import MessengerFactory

    results = []
    new_tg_id = telegram_message_id
    new_vk_id = vk_post_id

    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHANNEL_ID:
        try:
            telegram = MessengerFactory.create('telegram')
            if telegram_message_id:
                try:
                    result = await telegram.update_schedule(schedule_data, telegram_message_id)
                    new_tg_id = telegram_message_id
                except Exception:
                    logger.warning(f"Failed to edit Telegram message {telegram_message_id}, sending new")
                    result = await telegram.send_schedule(schedule_data)
                    new_tg_id = result.get('message_id')
            else:
                result = await telegram.send_schedule(schedule_data)
                new_tg_id = result.get('message_id')
            results.append({'channel': 'telegram', 'result': result})
        except Exception as e:
            logger.error(f"Failed to publish to Telegram: {e}")
            results.append({'channel': 'telegram', 'error': str(e)})

    if settings.VK_GROUP_TOKEN and settings.VK_GROUP_ID:
        try:
            vk = MessengerFactory.create('vk')
            if vk_post_id:
                try:
                    result = await vk.update_schedule(schedule_data, vk_post_id)
                    new_vk_id = vk_post_id
                except Exception:
                    logger.warning(f"Failed to edit VK post {vk_post_id}, sending new")
                    result = await vk.send_schedule(schedule_data)
                    new_vk_id = result.get('post_id')
            else:
                result = await vk.send_schedule(schedule_data)
                new_vk_id = result.get('post_id')
            results.append({'channel': 'vk', 'result': result})
        except Exception as e:
            logger.error(f"Failed to publish to VK: {e}")
            results.append({'channel': 'vk', 'error': str(e)})

    return results, new_tg_id, new_vk_id


@celery_app.task
def publish_schedule_to_channels(week_start: str, schedule_data: dict,
                                  telegram_message_id: int = None,
                                  vk_post_id: int = None):
    """Публикует или обновляет расписание во всех настроенных каналах."""
    from src.models.models import PublishedSchedule

    db = SessionLocal()
    try:
        results, new_tg_id, new_vk_id = asyncio.run(
            _publish_all(schedule_data, telegram_message_id, vk_post_id)
        )

        # Save message IDs back to PublishedSchedule
        week_start_date = datetime.fromisoformat(week_start).date()
        published = (
            db.query(PublishedSchedule)
            .filter(PublishedSchedule.week_start_date == week_start_date)
            .first()
        )
        if published:
            if new_tg_id:
                published.telegram_message_id = new_tg_id
            if new_vk_id:
                published.vk_post_id = new_vk_id
            published.updated_at = datetime.now()
            db.commit()

        return {"status": "success", "results": results}
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to publish schedule: {e}")
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
