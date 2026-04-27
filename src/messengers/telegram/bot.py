import asyncio
import logging
from typing import Dict, Any, Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

from src.config import settings
from src.messengers.interfaces.messenger import MessengerInterface
from src.business_logic import ScheduleService
from src.models import get_db

logger = logging.getLogger(__name__)


class TelegramBot(MessengerInterface):
    """Telegram bot implementation using Aiogram."""
    
    def __init__(self):
        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.channel_id = settings.TELEGRAM_CHANNEL_ID
        self.admin_ids = settings.TELEGRAM_ADMIN_IDS
        
        self._register_handlers()
    
    async def send_message(self, chat_id: str, text: str, **kwargs) -> Any:
        """Send a text message."""
        try:
            message = await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=kwargs.get('parse_mode', 'HTML'),
                reply_markup=kwargs.get('reply_markup'),
                disable_web_page_preview=kwargs.get('disable_web_page_preview', True)
            )
            return message.message_id
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            raise
    
    async def edit_message(self, chat_id: str, message_id: int, text: str, **kwargs) -> Any:
        """Edit an existing message."""
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode=kwargs.get('parse_mode', 'HTML'),
                reply_markup=kwargs.get('reply_markup'),
                disable_web_page_preview=kwargs.get('disable_web_page_preview', True)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to edit Telegram message: {e}")
            raise
    
    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        """Delete a message."""
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except Exception as e:
            logger.error(f"Failed to delete Telegram message: {e}")
            return False
    
    async def send_schedule(self, schedule_data: Dict, **kwargs) -> Dict:
        """Send schedule in appropriate format."""
        formatted_text = self._format_schedule(schedule_data)
        message_id = await self.send_message(
            chat_id=self.channel_id,
            text=formatted_text,
            **kwargs
        )
        return {
            'message_id': message_id,
            'channel': 'telegram',
            'chat_id': self.channel_id
        }
    
    async def update_schedule(self, schedule_data: Dict, message_id: int, **kwargs) -> Dict:
        """Update existing schedule message."""
        formatted_text = self._format_schedule(schedule_data)
        await self.edit_message(
            chat_id=self.channel_id,
            message_id=message_id,
            text=formatted_text,
            **kwargs
        )
        return {
            'message_id': message_id,
            'channel': 'telegram',
            'chat_id': self.channel_id
        }
    
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
            user = await self.bot.get_chat(user_id)
            return {
                'id': user.id,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
            }
        except Exception as e:
            logger.error(f"Failed to get user info for {user_id}: {e}")
            return {}
    
    def _format_schedule(self, schedule_data: Dict) -> str:
        """Format schedule data into Telegram message."""
        # This is a simplified version; should be enhanced based on actual data structure
        lines = ["<b>Расписание тренировок на следующую неделю:</b>\n"]
        
        for day in schedule_data.get('days', []):
            lines.append(f"\n<b>{day['day_name']} {day['date']}:</b>")
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
    
    # Bot handlers
    def _register_handlers(self):
        """Register Telegram bot command handlers."""
        
        @self.dp.message(Command("start"))
        async def cmd_start(message: Message):
            """Handle /start command."""
            await message.answer(
                "Привет! Я бот для записи на тренировки.\n"
                "Используйте /schedule чтобы посмотреть расписание,\n"
                "/book чтобы записаться на тренировку."
            )
        
        @self.dp.message(Command("schedule"))
        async def cmd_schedule(message: Message):
            """Send current schedule."""
            with next(get_db()) as db:
                service = ScheduleService(db)
                # Get schedule for current week
                from datetime import date
                today = date.today()
                week_start = today  # simplified
                schedule = service.get_week_schedule(week_start)
                
                formatted = self._format_schedule({'days': schedule})
                await message.answer(formatted, parse_mode='HTML')
        
        @self.dp.message(Command("book"))
        async def cmd_book(message: Message):
            """Start booking process."""
            # In real implementation, would use FSM for multi-step booking
            await message.answer(
                "Для записи на тренировку используйте кнопки ниже или "
                "обратитесь к администратору."
            )
        
        @self.dp.message(Command("admin"))
        async def cmd_admin(message: Message):
            """Admin commands."""
            if message.from_user.id not in self.admin_ids:
                await message.answer("У вас нет прав администратора.")
                return
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Создать расписание", callback_data="admin_create_schedule")],
                [InlineKeyboardButton(text="Опубликовать", callback_data="admin_publish")],
                [InlineKeyboardButton(text="Управление записями", callback_data="admin_manage_bookings")],
            ])
            await message.answer("Панель администратора:", reply_markup=keyboard)
    
    async def run(self):
        """Start the bot."""
        logger.info("Starting Telegram bot...")
        await self.dp.start_polling(self.bot)


# Register with factory
from src.messengers.interfaces.messenger import MessengerFactory
MessengerFactory.register("telegram", TelegramBot)