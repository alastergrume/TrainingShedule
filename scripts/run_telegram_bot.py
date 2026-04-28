"""Entry point for running the Telegram bot as a standalone process."""
import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


async def main():
    from src.config import settings

    if not settings.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN is not set, exiting.")
        sys.exit(1)

    from src.messengers.telegram.bot import TelegramBot
    bot = TelegramBot()
    logger.info("Telegram bot starting...")
    await bot.run()


if __name__ == '__main__':
    asyncio.run(main())
