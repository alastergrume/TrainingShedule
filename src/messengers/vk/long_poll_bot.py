import asyncio
from vkbottle.bot import Bot, Message
from src.config import vk_settings

bot = Bot(token=vk_settings.VK_GROUP_TOKEN)

@bot.on.message(text=["Привет", "Здравствуй", "/start"])
async def greet_handler(message: Message):
    await message.answer("Привет! Я бот этого сообщества")

@bot.on.message(text=["Что ты умеешь", "помощь", "/help"])
async def help_handler(message: Message):
    await message.answer(
        "Я умею:\n"
        "- отвечать на приветствия\n"
        "- Рассказывать о себе\n"
        "Напиши /start чтобы начать!"
    )

@bot.on.message()
async def fallback_handler(message: Message):
    await message.answer(
        "Не понял тебя, напиши /help чтобы узнать что я умею."
    )

if __name__ == '__main__':
    asyncio.run(bot.run_forever())
