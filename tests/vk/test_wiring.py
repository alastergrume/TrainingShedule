"""Routing: which handler a text or a button press reaches."""
from types import SimpleNamespace

import pytest
from vkbottle import GroupEventType

from src.messengers.vk.bot import AddTraining, PayloadCmd

MESSAGE_ROUTES = [
    ("начать", "h_start"),
    ("НАЧАТЬ", "h_start"),
    ("/start", "h_start"),
    ("расписание", "h_schedule"),
    ("Расписание", "h_schedule"),
    ("/schedule", "h_schedule"),
    ("записаться", "h_book"),
    ("/book", "h_book"),
    ("админ", "h_admin"),
    ("Админ", "h_admin"),
    ("/ADMIN", "h_admin"),
    ("отмена", "h_cancel"),
    ("/cancel", "h_cancel"),
]

UNROUTED_TEXT = ["привет", "когда расписание будет", "расписание на завтра", ""]

CALLBACK_ROUTES = [
    ("book_p:1", "cb_book_page"),
    ("book:42", "cb_book"),
    ("book:cancel", "cb_book"),
    ("a:menu", "cb_menu"),
    ("a:schedule", "cb_schedule"),
    ("a:gen:2026-10-12", "cb_generate"),
    ("a:publish", "cb_publish_menu"),
    ("a:pub:2026-10-12", "cb_publish"),
    ("a:pub_ok:2026-10-12", "cb_publish_confirm"),
    ("a:templates", "cb_templates"),
    ("a:templates:2", "cb_templates"),
    ("a:tmpl_add", "cb_tmpl_add_start"),
    ("a:tmpl:7", "cb_template_detail"),
    ("a:tmpl_del:7", "cb_template_delete"),
    ("a:tmpl_del_ok:7", "cb_template_delete_ok"),
    ("a:bookings", "cb_bookings"),
    ("a:bookings:1", "cb_bookings"),
    ("a:book_ok:3", "cb_booking_confirm"),
    ("a:book_no:3", "cb_booking_reject"),
    ("fsm_type:personal", "cb_fsm_type"),
    ("fsm_day:4", "cb_fsm_day"),
    ("fsm_confirm", "cb_fsm_confirm"),
    ("fsm_cancel", "cb_fsm_cancel"),
]


def test_handler_counts(bot):
    messages = bot._bot.labeler.message_view.handlers
    callbacks = bot._bot.labeler.raw_event_view.handlers[GroupEventType.MESSAGE_EVENT]
    assert len(messages) == 5 + 4   # 5 commands + 4 FSM text steps
    assert len(callbacks) == 20


@pytest.mark.parametrize("text, expected", MESSAGE_ROUTES)
async def test_command_routing_is_case_insensitive(find_message, text, expected):
    handler = await find_message(text)
    assert handler is not None and handler.__name__ == expected


@pytest.mark.parametrize("text", UNROUTED_TEXT)
async def test_free_text_outside_fsm_is_ignored(find_message, text):
    assert await find_message(text) is None


@pytest.mark.parametrize("state, text, expected", [
    (AddTraining.title, "Йога", "fsm_title"),
    (AddTraining.start_time, "19:30", "fsm_time"),
    (AddTraining.duration, "60", "fsm_duration"),
    (AddTraining.max_participants, "10", "fsm_max"),
    # steps that wait for a button must not swallow typed text
    (AddTraining.training_type, "что-то", None),
    (AddTraining.day_of_week, "что-то", None),
    # commands keep working in the middle of a dialog
    (AddTraining.title, "расписание", "h_schedule"),
    (AddTraining.title, "отмена", "h_cancel"),
    (AddTraining.start_time, "админ", "h_admin"),
])
async def test_text_routing_depends_on_fsm_state(find_message, state, text, expected):
    handler = await find_message(text, state=state)
    assert (handler.__name__ if handler else None) == expected


@pytest.mark.parametrize("cmd, expected", CALLBACK_ROUTES)
async def test_button_payload_routing(find_callback, cmd, expected):
    handler = await find_callback(cmd)
    assert handler is not None and handler.__name__ == expected


@pytest.mark.parametrize("cmd", ["zzz", "a:unknown", "", "book", "fsm_"])
async def test_unknown_payload_is_ignored(find_callback, cmd):
    assert await find_callback(cmd) is None


@pytest.mark.parametrize("payload", [None, {}, {"x": 1}, {"cmd": 5}, {"cmd": None}])
async def test_payload_rule_rejects_malformed_payloads(payload):
    event = SimpleNamespace(payload=payload)
    assert await PayloadCmd("a:menu").check(event) is False
    assert await PayloadCmd("a:", exact=False).check(event) is False


async def test_payload_rule_exact_vs_prefix():
    event = SimpleNamespace(payload={"cmd": "a:tmpl_del_ok:7"})
    assert await PayloadCmd("a:tmpl_del_ok:7").check(event) is True
    assert await PayloadCmd("a:tmpl_del:", exact=False).check(event) is False
    assert await PayloadCmd("a:tmpl_del_ok:", exact=False).check(event) is True
