"""MessengerInterface implementation: how VKBot talks to the VK API."""
from datetime import date
from types import SimpleNamespace

import pytest

from src.config import settings
from src.messengers.interfaces.messenger import MessengerFactory, MessengerInterface
from tests.vk import ADMIN_ID, USER_ID

GROUP_ID = 555


def test_registered_in_factory_and_implements_the_interface(bot):
    assert "vk" in MessengerFactory.get_available()
    assert isinstance(bot, MessengerInterface)
    assert not getattr(type(bot), "__abstractmethods__", None)


@pytest.mark.parametrize("ids, user, expected", [
    ([ADMIN_ID], ADMIN_ID, True),
    ([ADMIN_ID], USER_ID, False),
    ([], ADMIN_ID, False),
    ("", ADMIN_ID, False),       # unparsed value must not grant access
    (None, ADMIN_ID, False),
])
def test_is_admin(bot, monkeypatch, ids, user, expected):
    monkeypatch.setattr(settings, "VK_ADMIN_IDS", ids)

    assert bot._is_admin(user) is expected


# ── messages ─────────────────────────────────────────────────────────────────

async def test_send_message(bot):
    result = await bot.send_message("123", "hi", keyboard="KB", attachment="ATT")

    assert result == 1
    kwargs = bot.api.messages.send.await_args.kwargs
    assert kwargs["peer_id"] == 123
    assert kwargs["message"] == "hi"
    assert (kwargs["keyboard"], kwargs["attachment"]) == ("KB", "ATT")
    assert isinstance(kwargs["random_id"], int) and 0 <= kwargs["random_id"] < 2**31


async def test_send_message_error_propagates(bot):
    bot.api.messages.send.side_effect = RuntimeError("flood control")

    with pytest.raises(RuntimeError, match="flood control"):
        await bot.send_message("123", "hi")


async def test_edit_message(bot):
    result = await bot.edit_message("123", 9, "new text", keyboard="KB")

    assert result is True
    assert bot.api.messages.edit.await_args.kwargs == {
        "peer_id": 123, "message_id": 9, "message": "new text", "keyboard": "KB"}


async def test_edit_message_error_propagates(bot):
    bot.api.messages.edit.side_effect = RuntimeError("nope")

    with pytest.raises(RuntimeError):
        await bot.edit_message("123", 9, "x")


async def test_delete_message(bot):
    assert await bot.delete_message("123", 9) is True
    assert bot.api.messages.delete.await_args.kwargs == {
        "message_ids": [9], "delete_for_all": True}


async def test_delete_message_failure_returns_false(bot):
    bot.api.messages.delete.side_effect = RuntimeError("nope")

    assert await bot.delete_message("123", 9) is False


# ── wall posts (schedule publishing) ─────────────────────────────────────────

SCHEDULE = {"days": [{"date": "2026-10-12", "entries": []}]}


async def test_send_schedule_posts_to_the_group_wall(bot, fmt):
    result = await bot.send_schedule(SCHEDULE)

    assert result == {"post_id": 77, "channel": "vk", "group_id": GROUP_ID}
    assert bot.api.wall.post.await_args.kwargs == {
        "owner_id": -GROUP_ID, "message": "SCHEDULE_TEXT", "from_group": True}


async def test_send_schedule_parses_iso_dates_before_formatting(bot, fmt):
    await bot.send_schedule(SCHEDULE)

    assert fmt.week_calls[0][1] == date(2026, 10, 12)


async def test_send_schedule_falls_back_to_a_message_when_wall_fails(bot, fmt):
    bot.api.wall.post.side_effect = RuntimeError("access denied")

    result = await bot.send_schedule(SCHEDULE)

    assert result["channel"] == "vk" and result["chat_id"] == GROUP_ID
    assert result["message_id"] == 1
    assert bot.api.messages.send.await_args.kwargs["peer_id"] == GROUP_ID


async def test_send_schedule_without_days(bot, fmt):
    await bot.send_schedule({"days": []})

    assert bot.api.wall.post.await_args.kwargs["message"] == "Расписание недоступно"


async def test_update_schedule_edits_the_post(bot, fmt):
    result = await bot.update_schedule(SCHEDULE, 31)

    assert result == {"post_id": 31, "channel": "vk", "group_id": GROUP_ID}
    assert bot.api.wall.edit.await_args.kwargs == {
        "owner_id": -GROUP_ID, "post_id": 31, "message": "SCHEDULE_TEXT"}


async def test_update_schedule_error_propagates(bot, fmt):
    # the Celery publisher relies on this to fall back to a fresh post
    bot.api.wall.edit.side_effect = RuntimeError("post deleted")

    with pytest.raises(RuntimeError):
        await bot.update_schedule(SCHEDULE, 31)


async def test_check_post_exists(bot):
    assert await bot.check_post_exists(10) is True
    assert bot.api.wall.get_by_id.await_args.kwargs == {"posts": [f"-{GROUP_ID}_10"]}


async def test_check_post_exists_false_when_nothing_returned(bot):
    bot.api.wall.get_by_id.return_value = SimpleNamespace(items=[])

    assert await bot.check_post_exists(10) is False


async def test_check_post_exists_false_on_error(bot):
    bot.api.wall.get_by_id.side_effect = RuntimeError("nope")

    assert await bot.check_post_exists(10) is False


async def test_delete_post(bot):
    assert await bot.delete_post(10) is True
    assert bot.api.wall.delete.await_args.kwargs == {"owner_id": -GROUP_ID, "post_id": 10}


async def test_delete_post_failure_returns_false(bot):
    bot.api.wall.delete.side_effect = RuntimeError("nope")

    assert await bot.delete_post(10) is False


# ── reminders and user info ──────────────────────────────────────────────────

async def test_send_reminder(bot, fmt):
    assert await bot.send_reminder(str(USER_ID), {"id": 1}) is True

    kwargs = bot.api.messages.send.await_args.kwargs
    assert kwargs["peer_id"] == USER_ID and kwargs["message"] == "REMINDER_TEXT"


async def test_send_reminder_failure_returns_false(bot, fmt):
    bot.api.messages.send.side_effect = RuntimeError("blocked")

    assert await bot.send_reminder(str(USER_ID), {"id": 1}) is False


async def test_get_user_info(bot):
    assert await bot.get_user_info(str(USER_ID)) == {
        "id": USER_ID, "username": "ivan", "first_name": "Иван", "last_name": "Петров"}


async def test_get_user_info_unknown_user(bot):
    bot.api.users.get.return_value = []

    assert await bot.get_user_info("1") == {}


async def test_get_user_info_failure_returns_empty(bot):
    bot.api.users.get.side_effect = RuntimeError("nope")

    assert await bot.get_user_info("1") == {}
