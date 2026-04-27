import logging
import json
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
        """Send a text message."""
        try:
            # VK API is synchronous, so we wrap in thread if needed
            # For simplicity, we use sync call
            result = self.vk.messages.send(
                peer_id=int(chat_id),
                message=text,
                random_id=get_random_id(),
                keyboard=kwargs.get('keyboard'),
                attachment=kwargs.get('attachment')
            )
            return result
        except Exception as e:
            logger.error(f"Failed to send VK message: {e}")
            raise
    
    async def edit_message(self, chat_id: str, message_id: int, text: str, **kwargs) -> Any:
        """Edit an existing message."""
        # VK doesn't support editing messages directly via API
        # We'll delete and resend
        logger.warning("VK doesn't support message editing, will delete and resend")
        await self.delete_message(chat_id, message_id)
        return await self.send_message(chat_id, text, **kwargs)
    
    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        """Delete a message."""
        try:
            # VK API for deleting messages requires conversation_message_id
            # This is simplified
            self.vk.messages.delete(
                message_ids=message_id,
                delete_for_all=1
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete VK message: {e}")
            return False
    
    async def send_schedule(self, schedule_data: Dict, **kwargs) -> Dict:
        """Send schedule in appropriate format."""
        formatted_text = self._format_schedule(schedule_data)
        
        # Try to post to group wall
        try:
            post = self.vk.wall.post(
                owner_id=f"-{self.group_id}",
                message=formatted_text,
                from_group=1
            )
            post_id = post.get('post_id')
            return {
                'post_id': post_id,
                'channel': 'vk',
                'group_id': self.group_id
            }
        except Exception as e:
            logger.error(f"Failed to post to VK wall: {e}")
            # Fallback to sending to chat
            message_id = await self.send_message(
                chat_id=self.group_id,
                text=formatted_text
            )
            return {
                'message_id': message_id,
                'channel': 'vk',
                'chat_id': self.group_id
            }
    
    async def update_schedule(self, schedule_data: Dict, post_id: int, **kwargs) -> Dict:
        """Update existing schedule post."""
        formatted_text = self._format_schedule(schedule_data)
        
        try:
            self.vk.wall.edit(
                owner_id=f"-{self.group_id}",
                post_id=post_id,
                message=formatted_text
            )
            return {
                'post_id': post_id,
                'channel': 'vk',
                'group_id': self.group_id
            }
        except Exception as e:
            logger.error(f"Failed to edit VK post: {e}")
            raise
    
    async def send_reminder(self, user_id: str, reminder_data: Dict) -> bool:
        """Send reminder to user."""
        try:
            text = self._format_reminder(reminder_data)
            await self.send_message(
                chat_id=user_id,
                text=text
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send reminder to {user_id}: {e}")
            return False
    
    async def get_user_info(self, user_id: str) -> Dict:
        """Get user information."""
        try:
            users = self.vk.users.get(user_ids=user_id, fields='first_name,last_name,screen_name')
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
        """Format schedule data into VK message."""
        # Similar to Telegram formatting but with VK-specific markup
        lines = ["Расписание тренировок на следующую неделю:\n"]
        
        for day in schedule_data.get('days', []):
            lines.append(f"\n{day['day_name']} {day['date']}:")
            for entry in day['entries']:
                time = entry['time']
                title = entry['title']
                type_ = entry['type']
                
                if type_ == 'basic':
                    line = f"{time}- {title} (Базовая)"
                elif type_ == 'commercial':
                    line = f"{time}- {title}💸 (Коммерческая)"
                    # Add participants
                    for booking in entry['bookings']:
                        line += f"\n    - {booking['user_name']}"
                        if booking.get('paid'):
                            line += " ✅"
                else:  # personal
                    line = f"{time}- {title} (Персональная)"
                
                lines.append(line)
        
        lines.append("\n💸-коммерческая группа. Оплата 400₽ наличными или он-лайн переводом.")
        lines.append("Занимайте свободные места.❤️")
        
        return "\n".join(lines)
    
    def _format_reminder(self, reminder_data: Dict) -> str:
        """Format reminder message."""
        training = reminder_data.get('training', {})
        return (
            f"Напоминание о тренировке!\n"
            f"Тренировка: {training.get('title')}\n"
            f"Время: {training.get('time')}\n"
            f"Место: спортивный зал\n"
            f"Пожалуйста, подтвердите участие."
        )
    
    def process_event(self, event):
        """Process incoming VK event."""
        if event.type == VkBotEventType.MESSAGE_NEW:
            message = event.message
            text = message.text.lower()
            
            if text == 'начать' or text == '/start':
                self._handle_start(message)
            elif text == 'расписание' or text == '/schedule':
                self._handle_schedule(message)
            elif text == 'записаться' or text == '/book':
                self._handle_book(message)
    
    def _handle_start(self, message):
        """Handle start command."""
        response = (
            "Привет! Я бот для записи на тренировки.\n"
            "Используйте 'расписание' чтобы посмотреть расписание,\n"
            "'записаться' чтобы записаться на тренировку."
        )
        self.vk.messages.send(
            peer_id=message.peer_id,
            message=response,
            random_id=get_random_id()
        )
    
    def _handle_schedule(self, message):
        """Send current schedule."""
        # In real implementation, fetch from database
        response = "Расписание на неделю:\n(здесь будет расписание)"
        self.vk.messages.send(
            peer_id=message.peer_id,
            message=response,
            random_id=get_random_id()
        )
    
    def _handle_book(self, message):
        """Start booking process."""
        response = "Для записи на тренировку используйте кнопки ниже или обратитесь к администратору."
        self.vk.messages.send(
            peer_id=message.peer_id,
            message=response,
            random_id=get_random_id()
        )
    
    def run(self):
        """Start listening for events."""
        logger.info("Starting VK bot...")
        for event in self.longpoll.listen():
            self.process_event(event)


# Register with factory
from src.messengers.interfaces.messenger import MessengerFactory
MessengerFactory.register("vk", VKBot)