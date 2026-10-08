"""User-facing flows: start, schedule, booking."""
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.config import settings
from src.messengers.vk.bot import AddTraining
from src.models.enums import BookingStatus
from src.models.models import Booking, PublishedSchedule, ScheduleEntry, User
from tests.fakes import (
    answered_keyboard, answered_text, assert_vk_limits, day, edited_keyboard,
    edited_text, gen_entry, kb_cmds, kb_labels, make_booking, make_entry,
    make_training, make_user,
)
from tests.vk import ADMIN_ID, USER_ID


def this_monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


# ── start ────────────────────────────────────────────────────────────────────

async def test_start_greets_user_by_name(say, bot):
    message = await say("начать", from_id=USER_ID)

    text = answered_text(message)
    assert "Привет, Иван!" in text
    assert "админ" not in text
    assert bot.api.users.get.await_args.kwargs["user_ids"] == [str(USER_ID)]


async def test_start_hints_admin_panel_to_admins(say):
    message = await say("/start", from_id=ADMIN_ID)

    assert "админ — панель администратора" in answered_text(message)


async def test_start_falls_back_to_generic_name_when_lookup_fails(say, bot):
    bot.api.users.get.side_effect = RuntimeError("vk down")

    message = await say("начать", from_id=USER_ID)

    assert "Привет, друг!" in answered_text(message)


# ── schedule ─────────────────────────────────────────────────────────────────

async def test_schedule_shows_current_week(say, db, generator, fmt):
    fmt.week_text = "WEEK"

    message = await say("расписание", from_id=USER_ID)

    assert answered_text(message) == "WEEK"
    assert generator.calls == [this_monday()]
    assert fmt.week_calls[0][1] == this_monday()
    assert db.closed


async def test_schedule_is_truncated_to_vk_message_limit(say, generator, fmt):
    fmt.week_text = "x" * 5000

    message = await say("расписание", from_id=USER_ID)

    assert len(answered_text(message)) == 4000


async def test_schedule_failure_gives_friendly_message(say, db, generator, fmt):
    generator.error = RuntimeError("db is down")

    message = await say("расписание", from_id=USER_ID)

    assert answered_text(message) == "Не удалось получить расписание."
    assert db.closed


# ── booking list ─────────────────────────────────────────────────────────────

async def test_book_without_entries(say, generator):
    message = await say("записаться", from_id=USER_ID)

    assert answered_text(message) == "Нет доступных тренировок для записи."
    assert answered_keyboard(message) is None


async def test_book_lists_only_bookable_entries(say, generator):
    generator.days = [day(
        date(2026, 10, 14),
        gen_entry(1, "Йога", "personal"),
        gen_entry(2, "Зал", "basic"),                          # basic: not bookable
        gen_entry(3, "Бокс", "commercial", is_cancelled=True),  # cancelled
        gen_entry(4, "Бег", "commercial", time="08:00-09:00"),
    )]

    message = await say("записаться", from_id=USER_ID)

    keyboard = answered_keyboard(message)
    assert kb_cmds(keyboard) == ["book:1", "book:4", "book:cancel"]
    assert kb_labels(keyboard)[0] == "14.10 19:00 — Йога"
    assert kb_labels(keyboard)[1] == "14.10 08:00 — Бег"


async def test_book_includes_published_future_weeks(say, db, generator):
    db.given(PublishedSchedule, (datetime(2030, 1, 7),))

    await say("записаться", from_id=USER_ID)

    assert generator.calls == [this_monday(), date(2030, 1, 7)]


async def test_book_failure(say, db, generator):
    generator.error = RuntimeError("boom")

    message = await say("записаться", from_id=USER_ID)

    assert answered_text(message) == "Ошибка."
    assert db.closed


async def test_book_pagination(say, press, generator):
    generator.days = [day(date(2026, 10, 14),
                          *[gen_entry(i, f"T{i}", "personal") for i in range(1, 11)])]

    message = await say("записаться", from_id=USER_ID)
    first = answered_keyboard(message)
    assert kb_cmds(first) == ["book:1", "book:2", "book:3", "book:4",
                              "book_p:1", "book:cancel"]

    middle = edited_keyboard(await press("book_p:1", user_id=USER_ID))
    assert kb_cmds(middle) == ["book:5", "book:6", "book:7", "book:8",
                               "book_p:0", "book_p:2", "book:cancel"]

    last = edited_keyboard(await press("book_p:2", user_id=USER_ID))
    assert kb_cmds(last) == ["book:9", "book:10", "book_p:1", "book:cancel"]

    for keyboard in (first, middle, last):
        assert_vk_limits(keyboard)


# ── booking ──────────────────────────────────────────────────────────────────

@pytest.fixture
def entry(db):
    training = make_training(id=3, title="Бокс")
    entry = make_entry(id=5, training=training, when=datetime(2026, 10, 14, 19, 0))
    db.given(ScheduleEntry, entry)
    return entry


async def test_book_cancel(press):
    event = await press("book:cancel", user_id=USER_ID)

    event.send_empty_answer.assert_awaited_once()
    assert edited_text(event) == "Запись отменена."


async def test_book_unknown_entry(press, db):
    event = await press("book:999", user_id=USER_ID)

    assert edited_text(event) == "Тренировка не найдена."
    assert not db.added


async def test_booking_creates_user_with_vk_id_and_pending_booking(press, db, entry):
    event = await press("book:5", user_id=USER_ID)

    [user] = db.added_of(User)
    assert user.vk_id == USER_ID
    assert (user.first_name, user.last_name, user.username) == ("Иван", "Петров", "ivan")

    [booking] = db.added_of(Booking)
    assert booking.status == BookingStatus.PENDING
    assert booking.training_id == 3
    assert booking.schedule_entry_id == 5
    assert booking.user_id == user.id

    text = edited_text(event)
    assert "Заявка принята" in text and "Бокс" in text and "14.10.2026 в 19:00" in text
    assert db.closed


async def test_booking_reuses_existing_user(press, db, bot, entry):
    db.given(User, make_user(id=7, vk_id=USER_ID))

    await press("book:5", user_id=USER_ID)

    assert db.added_of(User) == []
    assert db.added_of(Booking)[0].user_id == 7
    bot.api.users.get.assert_not_awaited()


async def test_booking_notifies_every_admin(press, bot, entry, monkeypatch):
    monkeypatch.setattr(settings, "VK_ADMIN_IDS", [ADMIN_ID, 3003])

    await press("book:5", user_id=USER_ID)

    sent = bot.api.messages.send.await_args_list
    assert {call.kwargs["peer_id"] for call in sent} == {ADMIN_ID, 3003}
    text = sent[0].kwargs["message"]
    assert "Новая заявка" in text and "Бокс" in text and "Иван" in text


async def test_duplicate_booking_is_rejected(press, db, bot, entry):
    db.given(User, make_user(id=7, vk_id=USER_ID))
    db.given(Booking, make_booking(user_id=7, entry_id=5))

    event = await press("book:5", user_id=USER_ID)

    assert edited_text(event) == "Вы уже подали заявку на эту тренировку."
    assert db.added_of(Booking) == []
    bot.api.messages.send.assert_not_awaited()


async def test_admin_notification_failure_does_not_break_booking(press, db, bot, entry):
    bot.api.messages.send.side_effect = RuntimeError("blocked by user")

    event = await press("book:5", user_id=USER_ID)

    assert "Заявка принята" in edited_text(event)
    assert len(db.added_of(Booking)) == 1


async def test_booking_unexpected_error(press, db, entry):
    db.query = MagicMock(side_effect=RuntimeError("db is down"))

    event = await press("book:5", user_id=USER_ID)

    assert edited_text(event) == "Ошибка при записи."
    assert db.closed


# ── cancel ───────────────────────────────────────────────────────────────────

async def test_cancel_resets_dialog(say, bot, fsm_state):
    await bot._bot.state_dispenser.set(USER_ID, AddTraining.title, title="X")

    message = await say("отмена", from_id=USER_ID)

    assert await fsm_state(USER_ID) is None
    assert answered_text(message).startswith("Отменено")
