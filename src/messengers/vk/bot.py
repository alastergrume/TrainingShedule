import asyncio
import logging
from typing import Dict, Any, Optional
import vk_api
from vk_api.bot_longpoll import VkBotLongPoll, VkBotEventType
from vk_api.utils import get_random_id

from src.config import settings
from src.messengers.interfaces.messenger import MessengerInterface

logger = logging.getLogger(__name__)


class VKBot(MessengerInterface):
    """VK bot implementation using vk-api."""

    def __init__(self):
        self.group_token = settings.VK_GROUP_TOKEN
        self.group_id = settings.VK_GROUP_ID
        self.confirmation_code = settings.VK_CONFIRMATION_CODE
        self.secret_key = settings.VK_SECRET_KEY

        self.vk_session = vk_api.VkApi(token=self.group_token)
        self.vk = self.vk_session.get_api()
        self.longpoll = VkBotLongPoll(self.vk_session, self.group_id)

    async def send_message(self, chat_id: str, text: str, **kwargs) -> Any:
        try:
            result = await asyncio.to_thread(
                self.vk.messages.send,
                peer_id=int(chat_id),
                message=text,
                random_id=get_random_id(),
                keyboard=kwargs.get('keyboard'),
                attachment=kwargs.get('attachment'),
            )
            return result
        except Exception as e:
            logger.error(f"Failed to send VK message: {e}")
            raise

    async def edit_message(self, chat_id: str, message_id: int, text: str, **kwargs) -> Any:
        # VK не поддерживает редактирование — удаляем и отправляем заново
        logger.warning("VK doesn't support message editing, will delete and resend")
        await self.delete_message(chat_id, message_id)
        return await self.send_message(chat_id, text, **kwargs)

    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        try:
            await asyncio.to_thread(
                self.vk.messages.delete,
                message_ids=message_id,
                delete_for_all=1,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete VK message: {e}")
            return False

    async def send_schedule(self, schedule_data: Dict, **kwargs) -> Dict:
        formatted_text = self._format_schedule(schedule_data)
        try:
            post = await asyncio.to_thread(
                self.vk.wall.post,
                owner_id=f"-{self.group_id}",
                message=formatted_text,
                from_group=1,
            )
            post_id = post.get('post_id')
            return {'post_id': post_id, 'channel': 'vk', 'group_id': self.group_id}
        except Exception as e:
            logger.error(f"Failed to post to VK wall: {e}")
            message_id = await self.send_message(chat_id=str(self.group_id), text=formatted_text)
            return {'message_id': message_id, 'channel': 'vk', 'chat_id': self.group_id}

    async def update_schedule(self, schedule_data: Dict, post_id: int, **kwargs) -> Dict:
        formatted_text = self._format_schedule(schedule_data)
        try:
            await asyncio.to_thread(
                self.vk.wall.edit,
                owner_id=f"-{self.group_id}",
                post_id=post_id,
                message=formatted_text,
            )
            return {'post_id': post_id, 'channel': 'vk', 'group_id': self.group_id}
        except Exception as e:
            logger.error(f"Failed to edit VK post: {e}")
            raise

    async def send_reminder(self, user_id: str, reminder_data: Dict) -> bool:
        try:
            text = self._format_reminder(reminder_data)
            await self.send_message(chat_id=user_id, text=text)
            return True
        except Exception as e:
            logger.error(f"Failed to send VK reminder to {user_id}: {e}")
            return False

    async def get_user_info(self, user_id: str) -> Dict:
        try:
            users = await asyncio.to_thread(
                self.vk.users.get,
                user_ids=user_id,
                fields='first_name,last_name,screen_name',
            )
            if users:
                user = users[0]
                return {
                    'id': user['id'],
                    'username': user.get('screen_name'),
                    'first_name': user.get('first_name'),
                    'last_name': user.get('last_name'),
                }
            return {}
        except Exception as e:
            logger.error(f"Failed to get VK user info for {user_id}: {e}")
            return {}

    def _format_schedule(self, schedule_data: Dict) -> str:
        from src.utils.formatter import ScheduleFormatter
        days = schedule_data.get('days', [])
        if days:
            from datetime import date
            week_start = days[0].get('date', date.today())
            return ScheduleFormatter.format_week_schedule(days, week_start)
        return "Расписание недоступно"

    def _format_reminder(self, reminder_data: Dict) -> str:
        from src.utils.formatter import ScheduleFormatter
        return ScheduleFormatter.format_reminder(reminder_data)

    # --- Синхронные обработчики событий (longpoll — sync контекст) ---

    def process_event(self, event):
        if event.type == VkBotEventType.MESSAGE_NEW:
            message = event.message
            text = message.text.lower()

            if text in ('начать', '/start'):
                self._handle_start(message)
            elif text in ('расписание', '/schedule'):
                self._handle_schedule(message)
            elif text in ('записаться', '/book'):
                self._handle_book(message)

    def _handle_start(self, message):
        self.vk.messages.send(
            peer_id=message.peer_id,
            message=(
                "Привет! Я бот для записи на тренировки.\n"
                "Напишите 'расписание' чтобы посмотреть расписание,\n"
                "'записаться' чтобы подать заявку на тренировку."
            ),
            random_id=get_random_id(),
        )

    def _handle_schedule(self, message):
        from src.models.base import SessionLocal
        from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
        from datetime import date

        db = SessionLocal()
        try:
            today = date.today()
            week_start = today - __import__('datetime').timedelta(days=today.weekday())
            days = ScheduleGenerator.generate_from_db(db, week_start)
            text = ScheduleFormatter.format_week_schedule(days, week_start)
        except Exception as e:
            logger.error(f"Failed to fetch schedule for VK: {e}")
            text = "Не удалось получить расписание. Попробуйте позже."
        finally:
            db.close()

        self.vk.messages.send(
            peer_id=message.peer_id,
            message=text,
            random_id=get_random_id(),
        )

    def _handle_book(self, message):
        self.vk.messages.send(
            peer_id=message.peer_id,
            message="Для записи на тренировку обратитесь к администратору.",
            random_id=get_random_id(),
        )

    def run(self):
        logger.info("Starting VK bot...")
        for event in self.longpoll.listen():
            self.process_event(event)


# Register with factory
from src.messengers.interfaces.messenger import MessengerFactory
MessengerFactory.register("vk", VKBot)
