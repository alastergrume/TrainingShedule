"""Admin panel: access control, schedule, publishing, templates, bookings."""
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from src.models.enums import BookingStatus, TrainingType
from src.models.models import Booking, ScheduleEntry, Training, User
from tests.fakes import (
    answered_keyboard, answered_text, assert_vk_limits, day, edited_keyboard,
    edited_text, gen_entry, kb_buttons, kb_cmds, kb_labels, make_booking,
    make_entry, make_training, make_user,
)
from tests.vk import ADMIN_ID, USER_ID

ADMIN_ONLY = [
    "a:menu", "a:schedule", "a:gen:2026-10-12", "a:publish", "a:pub:2026-10-12",
    "a:pub_ok:2026-10-12", "a:templates", "a:templates:1", "a:tmpl_add",
    "a:tmpl:1", "a:tmpl_del:1", "a:tmpl_del_ok:1", "a:bookings", "a:bookings:1",
    "a:book_ok:1", "a:book_no:1",
]


def monday(weeks=0):
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=weeks)


# ── access control ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("cmd", ADMIN_ONLY)
async def test_admin_buttons_reject_non_admins(press, db, cmd):
    event = await press(cmd, user_id=USER_ID)

    event.show_snackbar.assert_awaited_once_with("Нет доступа")
    event.edit_message.assert_not_awaited()
    assert db.commits == 0 and not db.added


@pytest.mark.parametrize("cmd", ADMIN_ONLY)
async def test_admin_buttons_always_acknowledge_the_press(
        press, cmd, generator, fmt, schedule_service, celery):
    # without send_empty_answer the VK button keeps spinning
    event = await press(cmd, user_id=ADMIN_ID)

    event.send_empty_answer.assert_awaited_once()


async def test_admin_command_rejects_non_admins(say):
    message = await say("админ", from_id=USER_ID)

    assert answered_text(message) == "У вас нет прав администратора."
    assert answered_keyboard(message) is None


@pytest.mark.parametrize("text", ["админ", "/admin", "Админ"])
async def test_admin_command_opens_panel(say, text):
    message = await say(text, from_id=ADMIN_ID)

    keyboard = answered_keyboard(message)
    assert answered_text(message) == "Панель администратора:"
    assert kb_cmds(keyboard) == ["a:schedule", "a:publish", "a:templates", "a:bookings"]
    [link] = [a for a in kb_buttons(keyboard) if a["type"] == "open_link"]
    assert link["link"] == "https://example.test/miniapp"
    assert_vk_limits(keyboard)


async def test_menu_button_returns_to_panel(press):
    event = await press("a:menu")

    assert edited_text(event) == "Панель администратора:"
    assert "a:schedule" in kb_cmds(edited_keyboard(event))


# ── schedule generation ──────────────────────────────────────────────────────

async def test_schedule_menu_offers_current_and_next_week(press):
    event = await press("a:schedule")

    assert kb_cmds(edited_keyboard(event)) == [
        f"a:gen:{monday(0).isoformat()}",
        f"a:gen:{monday(1).isoformat()}",
        "a:menu",
    ]


async def test_generate_calls_service_and_offers_publish(press, db, schedule_service):
    event = await press("a:gen:2026-10-12")

    service = schedule_service.return_value
    service.generate_weekly_schedule.assert_called_once_with(date(2026, 10, 12))
    assert "Сгенерировано 3 занятий" in edited_text(event)
    assert "12.10–18.10" in edited_text(event)
    assert kb_cmds(edited_keyboard(event)) == ["a:pub:2026-10-12", "a:schedule"]
    assert db.closed


async def test_generate_failure_is_reported(press, db, schedule_service):
    schedule_service.return_value.generate_weekly_schedule.side_effect = ValueError("boom")

    event = await press("a:gen:2026-10-12")

    assert edited_text(event) == "Ошибка: boom"
    assert kb_cmds(edited_keyboard(event)) == ["a:schedule"]
    assert db.closed


# ── publishing ───────────────────────────────────────────────────────────────

async def test_publish_menu_offers_current_and_next_week(press):
    event = await press("a:publish")

    assert kb_cmds(edited_keyboard(event)) == [
        f"a:pub:{monday(0).isoformat()}",
        f"a:pub:{monday(1).isoformat()}",
        "a:menu",
    ]


async def test_publish_shows_preview_with_confirmation(press, generator, fmt):
    fmt.week_text = "PREVIEW"

    event = await press("a:pub:2026-10-12")

    assert edited_text(event).startswith("Превью расписания 12.10–18.10:")
    assert "PREVIEW" in edited_text(event)
    assert generator.calls == [date(2026, 10, 12)]
    assert kb_cmds(edited_keyboard(event)) == ["a:pub_ok:2026-10-12", "a:publish"]


async def test_publish_preview_is_truncated(press, generator, fmt):
    fmt.week_text = "x" * 5000

    event = await press("a:pub:2026-10-12")

    assert len(edited_text(event)) <= 4000
    assert edited_text(event).endswith("...")


async def test_publish_preview_failure(press, db, generator, fmt):
    generator.error = RuntimeError("boom")

    event = await press("a:pub:2026-10-12")

    assert edited_text(event) == "Ошибка: boom"
    assert kb_cmds(edited_keyboard(event)) == ["a:publish"]
    assert db.closed


async def test_publish_confirm_saves_and_queues_for_all_channels(
        press, generator, fmt, schedule_service, celery):
    generator.days = [day(date(2026, 10, 12), gen_entry(1))]
    fmt.week_text = "CONTENT"

    event = await press("a:pub_ok:2026-10-12")

    schedule_service.return_value.publish_schedule.assert_called_once_with(
        date(2026, 10, 12), "CONTENT")
    celery.delay.assert_called_once()
    week, payload = celery.delay.call_args.args
    assert week == "2026-10-12"
    # dates must be JSON-serialisable for the Celery broker
    assert payload["days"][0]["date"] == "2026-10-12"
    assert "опубликовано" in edited_text(event)
    assert kb_cmds(edited_keyboard(event)) == ["a:menu"]


async def test_publish_confirm_reports_broker_failure(
        press, generator, fmt, schedule_service, celery):
    celery.delay.side_effect = RuntimeError("redis down")

    event = await press("a:pub_ok:2026-10-12")

    assert edited_text(event) == "Ошибка публикации: redis down"


# ── templates ────────────────────────────────────────────────────────────────

def _trainings(n):
    return [make_training(id=i, title=f"T{i}", day=0, start=f"1{i}:00") for i in range(1, n + 1)]


async def test_templates_first_page(press, db):
    db.given(Training, *_trainings(9))

    event = await press("a:templates")

    keyboard = edited_keyboard(event)
    assert "(9)" in edited_text(event)
    assert kb_cmds(keyboard) == ["a:tmpl:1", "a:tmpl:2", "a:tmpl:3", "a:tmpl:4",
                                 "a:templates:1", "a:tmpl_add", "a:menu"]
    assert kb_labels(keyboard)[0] == "По 11:00 — T1"
    assert_vk_limits(keyboard)


async def test_templates_middle_page_has_both_arrows(press, db):
    db.given(Training, *_trainings(9))

    keyboard = edited_keyboard(await press("a:templates:1"))

    assert kb_cmds(keyboard) == ["a:tmpl:5", "a:tmpl:6", "a:tmpl:7", "a:tmpl:8",
                                 "a:templates:0", "a:templates:2", "a:tmpl_add", "a:menu"]
    assert_vk_limits(keyboard)


async def test_templates_last_page(press, db):
    db.given(Training, *_trainings(9))

    keyboard = edited_keyboard(await press("a:templates:2"))

    assert kb_cmds(keyboard) == ["a:tmpl:9", "a:templates:1", "a:tmpl_add", "a:menu"]


async def test_templates_empty_still_allows_adding(press, db):
    event = await press("a:templates")

    assert "(0)" in edited_text(event)
    assert kb_cmds(edited_keyboard(event)) == ["a:tmpl_add", "a:menu"]


async def test_template_detail(press, db):
    db.given(Training, make_training(
        id=7, title="Йога", type_=TrainingType.COMMERCIAL, day=2, start="19:30",
        duration=90, max_participants=12, description="Для начинающих"))

    event = await press("a:tmpl:7")

    text = edited_text(event)
    for expected in ("Йога", "Коммерческая", "Среда", "19:30, 90 мин.", "12",
                     "Для начинающих"):
        assert expected in text
    assert kb_cmds(edited_keyboard(event)) == ["a:tmpl_del:7", "a:templates"]


async def test_template_detail_defaults(press, db):
    db.given(Training, make_training(id=7, max_participants=None, description=None))

    text = edited_text(await press("a:tmpl:7"))

    assert "без ограничений" in text
    assert "Описание: —" in text


async def test_template_detail_not_found(press):
    event = await press("a:tmpl:404")

    event.show_snackbar.assert_awaited_once_with("Не найдено")
    event.edit_message.assert_not_awaited()


async def test_template_delete_asks_for_confirmation_first(press, db):
    training = make_training(id=7)
    db.given(Training, training)

    event = await press("a:tmpl_del:7")

    assert edited_text(event) == "Удалить этот шаблон?"
    assert kb_cmds(edited_keyboard(event)) == ["a:tmpl_del_ok:7", "a:templates"]
    assert training.is_active is True and db.commits == 0


async def test_template_delete_deactivates_instead_of_removing(press, db):
    training = make_training(id=7)
    db.given(Training, training)

    event = await press("a:tmpl_del_ok:7")

    assert training.is_active is False
    assert db.commits == 1
    assert "Шаблон удалён" in edited_text(event)
    assert db.closed


# ── bookings ─────────────────────────────────────────────────────────────────

def _pending(db, n):
    db.given(Booking, *[make_booking(id=i) for i in range(1, n + 1)])
    db.given(User, make_user(id=7, first_name="Анна", last_name="Смирнова"))
    db.given(ScheduleEntry, make_entry(id=5, training=make_training(title="Бокс")))


async def test_bookings_empty(press):
    event = await press("a:bookings")

    assert "Нет заявок" in edited_text(event)
    assert kb_cmds(edited_keyboard(event)) == ["a:menu"]


async def test_bookings_list_has_confirm_and_reject_per_booking(press, db):
    _pending(db, 2)

    event = await press("a:bookings")

    keyboard = edited_keyboard(event)
    assert "(2)" in edited_text(event)
    assert kb_cmds(keyboard) == ["a:book_ok:1", "a:book_no:1",
                                 "a:book_ok:2", "a:book_no:2", "a:menu"]
    assert kb_labels(keyboard)[0] == "✅ Анна Смирнова / Бокс 14.10 19:00"


async def test_bookings_pagination(press, db):
    _pending(db, 7)

    first = edited_keyboard(await press("a:bookings"))
    middle = edited_keyboard(await press("a:bookings:1"))
    last = edited_keyboard(await press("a:bookings:2"))

    assert kb_cmds(first)[-2:] == ["a:bookings:1", "a:menu"]
    assert kb_cmds(middle)[-3:] == ["a:bookings:0", "a:bookings:2", "a:menu"]
    assert kb_cmds(last) == ["a:book_ok:7", "a:book_no:7", "a:bookings:1", "a:menu"]
    for keyboard in (first, middle, last):
        assert_vk_limits(keyboard)


@pytest.fixture
def pending_booking(db):
    booking = make_booking(id=1, user_id=7)
    db.given(Booking, booking)
    db.given(User, make_user(id=7, vk_id=USER_ID))
    db.given(ScheduleEntry, make_entry(id=5, training=make_training(title="Бокс")))
    return booking


async def test_confirm_booking_notifies_the_user(press, db, bot, pending_booking):
    event = await press("a:book_ok:1")

    assert pending_booking.status == BookingStatus.CONFIRMED
    assert db.commits == 1
    sent = bot.api.messages.send.await_args.kwargs
    assert sent["peer_id"] == USER_ID
    assert "подтверждена" in sent["message"] and "Бокс" in sent["message"]
    assert edited_text(event) == "✅ Заявка #1 подтверждена."
    assert kb_cmds(edited_keyboard(event)) == ["a:bookings"]


async def test_reject_booking_records_reason_and_notifies(press, db, bot, pending_booking):
    event = await press("a:book_no:1")

    assert pending_booking.status == BookingStatus.CANCELLED
    assert pending_booking.notes == "Отклонено администратором"
    assert "отклонена" in bot.api.messages.send.await_args.kwargs["message"]
    assert edited_text(event) == "❌ Заявка #1 отклонена."


async def test_decision_for_user_without_vk_id_sends_nothing(press, db, bot, pending_booking):
    db.given(User, make_user(id=7, vk_id=None))   # e.g. a Telegram-only user

    event = await press("a:book_ok:1")

    assert pending_booking.status == BookingStatus.CONFIRMED
    bot.api.messages.send.assert_not_awaited()
    assert "подтверждена" in edited_text(event)


async def test_notification_failure_does_not_break_decision(press, bot, pending_booking):
    bot.api.messages.send.side_effect = RuntimeError("user blocked the group")

    event = await press("a:book_ok:1")

    assert pending_booking.status == BookingStatus.CONFIRMED
    assert "подтверждена" in edited_text(event)


@pytest.mark.parametrize("cmd", ["a:book_ok:404", "a:book_no:404"])
async def test_decision_for_missing_booking(press, db, cmd):
    event = await press(cmd)

    event.show_snackbar.assert_awaited_once_with("Заявка не найдена")
    event.edit_message.assert_not_awaited()
    assert db.commits == 0


async def test_decision_unexpected_error(press, db):
    db.query = MagicMock(side_effect=RuntimeError("db is down"))

    event = await press("a:book_ok:1")

    assert edited_text(event).startswith("Ошибка:")
    assert db.closed
