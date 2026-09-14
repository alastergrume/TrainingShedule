"""
Invite VK friends to a community.

Usage:
    python scripts/vk_invite_friends.py

Requires in .env:
    VK_USER_TOKEN  — user token with friends,groups scope
    VK_GROUP_ID    — numeric community ID
    VK_GROUP_TOKEN — community token (for getting member list)

Progress is saved to scripts/invite_progress.json so the script
can be re-run daily until all friends are processed.
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

from vkbottle import API

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

PROGRESS_FILE = Path(__file__).parent / "invite_progress.json"
DAILY_LIMIT = 40
DELAY_SECONDS = 3


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"invited": [], "errors": {}}


def save_progress(progress: dict):
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def main():
    if not settings.VK_USER_TOKEN:
        log.error("VK_USER_TOKEN is not set in .env")
        return
    if not settings.VK_GROUP_ID:
        log.error("VK_GROUP_ID is not set in .env")
        return

    user_api = API(token=settings.VK_USER_TOKEN)
    group_api = API(token=settings.VK_GROUP_TOKEN)

    log.info("Getting friends list...")
    friends_resp = await user_api.friends.get()
    friends = set(friends_resp.items)
    log.info(f"Total friends: {len(friends)}")

    log.info("Getting group members...")
    members_resp = await group_api.groups.get_members(group_id=settings.VK_GROUP_ID)
    members = set(members_resp.items)
    log.info(f"Already in group: {len(members)}")

    progress = load_progress()
    processed = set(progress["invited"]) | {int(k) for k in progress["errors"]}

    to_invite = sorted(friends - members - processed)
    log.info(f"To invite: {min(len(to_invite), DAILY_LIMIT)} today ({len(to_invite)} remaining)")

    sent = 0
    for uid in to_invite:
        if sent >= DAILY_LIMIT:
            log.info(f"Daily limit ({DAILY_LIMIT}) reached.")
            break

        try:
            await user_api.request("groups.invite", {"group_id": settings.VK_GROUP_ID, "user_id": uid})
            progress["invited"].append(uid)
            sent += 1
            log.info(f"[{sent}/{DAILY_LIMIT}] Invited {uid}")
        except Exception as e:
            err = str(e)
            if "captcha" in err.lower() or "[14]" in err:
                log.error("Captcha required — stopping. Run again later.")
                save_progress(progress)
                return
            progress["errors"][str(uid)] = err
            log.warning(f"Skipped {uid}: {err}")

        save_progress(progress)
        await asyncio.sleep(DELAY_SECONDS)

    remaining = len(to_invite) - sent
    log.info(
        f"Done. Invited today: {sent}. "
        f"Total invited: {len(progress['invited'])}. "
        f"Errors: {len(progress['errors'])}. "
        f"Remaining: ~{remaining}"
    )


if __name__ == "__main__":
    asyncio.run(main())
