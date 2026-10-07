import logging
import random
import re
from typing import Dict, Any, Optional
from vkbottle import API
from vkbottle.bot import Bot, Message
from vkbottle.dispatch.rules.base import VBMLRule

from src.config import settings
from src.messengers.interfaces.messenger import MessengerInterface

logger = logging.getLogger(__name__)


def _random_id() -> int:
    """VK требует random_id для дедупликации сообщений."""
    return random.getrandbits(31)


class VKBot(MessengerInterface):
    """VK bot implementation using vkbottle."""

    def __init__(self):
        self.group_token = settings.VK_GROUP_TOKEN
        self.group_id = settings.VK_GROUP_ID

        self.api = API(token=self.group_token)
        self._bot: Optional[Bot] = None

    async def send_message(self, chat_id: str, text: str, **kwargs) -> Any:
        try:
            return await self.api.messages.send(
                peer_id=int(chat_id),
                message=text,
                random_id=_random_id(),
                keyboard=kwargs.get('keyboard'),
                attachment=kwargs.get('attachment'),
            )
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
            await self.api.messages.delete(
                message_ids=[message_id],
                delete_for_all=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete VK message: {e}")
            return False

    async def send_schedule(self, schedule_data: Dict, **kwargs) -> Dict:
        formatted_text = self._format_schedule(schedule_data)
        try:
            post = await self.api.wall.post(
                owner_id=-self.group_id,
                message=formatted_text,
                from_group=True,
            )
            return {'post_id': post.post_id, 'channel': 'vk', 'group_id': self.group_id}
        except Exception as e:
            logger.error(f"Failed to post to VK wall: {e}")
            message_id = await self.send_message(chat_id=str(self.group_id), text=formatted_text)
            return {'message_id': message_id, 'channel': 'vk', 'chat_id': self.group_id}

    async def update_schedule(self, schedule_data: Dict, post_id: int, **kwargs) -> Dict:
        formatted_text = self._format_schedule(schedule_data)
        try:
            await self.api.wall.edit(
                owner_id=-self.group_id,
                post_id=post_id,
                message=formatted_text,
            )
            return {'post_id': post_id, 'channel': 'vk', 'group_id': self.group_id}
        except Exception as e:
            logger.error(f"Failed to edit VK post: {e}")
            raise

    async def check_post_exists(self, post_id: int) -> bool:
        try:
            result = await self.api.wall.get_by_id(
                posts=[f"-{self.group_id}_{post_id}"],
            )
            return bool(result.items)
        except Exception:
            return False

    async def delete_post(self, post_id: int) -> bool:
        try:
            await self.api.wall.delete(
                owner_id=-self.group_id,
                post_id=post_id,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete VK post {post_id}: {e}")
            return False

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
            users = await self.api.users.get(
                user_ids=[user_id],
                fields=['screen_name'],
            )
            if users:
                user = users[0]
                return {
                    'id': user.id,
                    'username': user.screen_name,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
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

    # --- Обработчики сообщений (vkbottle longpoll) ---

    async def _handle_start(self, message: Message):
        await message.answer(
            "Привет! Я бот для записи на тренировки.\n"
            "Напишите 'расписание' чтобы посмотреть расписание,\n"
            "'записаться' чтобы подать заявку на тренировку."
        )

    async def _handle_schedule(self, message: Message):
        from src.models.base import SessionLocal
        from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
        from datetime import date, timedelta

        db = SessionLocal()
        try:
            today = date.today()
            week_start = today - timedelta(days=today.weekday())
            days = ScheduleGenerator.generate_from_db(db, week_start)
            text = ScheduleFormatter.format_week_schedule(days, week_start)
        except Exception as e:
            logger.error(f"Failed to fetch schedule for VK: {e}")
            text = "Не удалось получить расписание. Попробуйте позже."
        finally:
            db.close()

        await message.answer(text)

    async def _handle_book(self, message: Message):
        await message.answer("Для записи на тренировку обратитесь к администратору.")

    @staticmethod
    def _text_rule(*variants: str) -> VBMLRule:
        # IGNORECASE — команды независимы от регистра
        return VBMLRule(list(variants), flags=re.IGNORECASE | re.DOTALL)

    def _build_bot(self) -> Bot:
        bot = Bot(api=self.api)
        bot.on.message(self._text_rule("начать", "/start"))(self._handle_start)
        bot.on.message(self._text_rule("расписание", "/schedule"))(self._handle_schedule)
        bot.on.message(self._text_rule("записаться", "/book"))(self._handle_book)
        return bot

    async def run(self):
        logger.info("Starting VK bot...")
        if self._bot is None:
            self._bot = self._build_bot()
        await self._bot.run_polling()


# Register with factory
from src.messengers.interfaces.messenger import MessengerFactory
MessengerFactory.register("vk", VKBot)
