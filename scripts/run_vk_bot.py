"""Entry point for running the VK bot as a standalone process."""
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

    if not settings.VK_GROUP_TOKEN:
        logger.error("VK_GROUP_TOKEN is not set, exiting.")
        sys.exit(1)

    from src.messengers.vk.bot import VKBot
    bot = VKBot()
    logger.info("VK bot starting...")
    await bot.run()


if __name__ == '__main__':
    asyncio.run(main())
