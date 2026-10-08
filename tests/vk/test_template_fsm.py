"""The multi-step dialog for adding a training template."""
from unittest.mock import MagicMock

import pytest

from src.messengers.vk.bot import AddTraining
from src.models.enums import TrainingType
from src.models.models import Training
from tests.fakes import (
    answered_keyboard, answered_text, edited_keyboard, edited_text, kb_cmds,
)
from tests.vk import ADMIN_ID, USER_ID


async def _enter(bot, state, **data):
    """Put the admin straight into a dialog step."""
    await bot._bot.state_dispenser.set(ADMIN_ID, state, **data)


async def test_full_dialog_creates_the_template(press, say, bot, db, fsm_state, fsm_data):
    event = await press("a:tmpl_add")
    assert await fsm_state() == "AddTraining:title"
    assert "название" in edited_text(event)

    message = await say("Вечерняя йога")
    assert await fsm_state() == "AddTraining:training_type"
    assert kb_cmds(answered_keyboard(message)) == [
        "fsm_type:personal", "fsm_type:commercial", "fsm_type:basic"]

    event = await press("fsm_type:commercial")
    assert await fsm_state() == "AddTraining:day_of_week"
    assert kb_cmds(edited_keyboard(event)) == [f"fsm_day:{i}" for i in range(7)]

    await press("fsm_day:2")
    assert await fsm_state() == "AddTraining:start_time"

    await say("19:30")
    assert await fsm_state() == "AddTraining:duration"

    await say("90")
    assert await fsm_state() == "AddTraining:max_participants"

    message = await say("12")
    summary = answered_text(message)
    for expected in ("Вечерняя йога", "Коммерческая", "Среда", "19:30, 90 мин.", "12"):
        assert expected in summary
    assert kb_cmds(answered_keyboard(message)) == ["fsm_confirm", "fsm_cancel"]
    assert await fsm_data() == {
        "title": "Вечерняя йога", "training_type": "commercial", "day_of_week": 2,
        "start_time": "19:30", "duration_minutes": 90, "max_participants": 12,
    }

    event = await press("fsm_confirm")

    [training] = db.added_of(Training)
    assert training.title == "Вечерняя йога"
    assert training.training_type == TrainingType.COMMERCIAL
    assert training.day_of_week == 2
    assert training.start_time == "19:30"
    assert training.duration_minutes == 90
    assert training.max_participants == 12
    assert training.is_active is True
    assert db.commits == 1 and db.closed
    assert "Вечерняя йога" in edited_text(event) and "добавлен" in edited_text(event)
    assert kb_cmds(edited_keyboard(event)) == ["a:templates"]
    assert await fsm_state() is None


@pytest.mark.parametrize("answer", ["пропустить", "Пропустить"])
async def test_skip_means_unlimited_participants(say, bot, db, press, fsm_data, answer):
    await _enter(bot, AddTraining.max_participants, title="T", training_type="basic",
                 day_of_week=1, start_time="10:00", duration_minutes=45)

    message = await say(answer)

    assert "без ограничений" in answered_text(message)
    assert (await fsm_data())["max_participants"] is None
    await press("fsm_confirm")
    assert db.added_of(Training)[0].max_participants is None


@pytest.mark.parametrize("step, bad_input, expected_error", [
    (AddTraining.start_time, "abc", "Формат: ЧЧ:ММ"),
    (AddTraining.start_time, "7pm", "Формат: ЧЧ:ММ"),
    (AddTraining.duration, "час", "Введите число минут"),
    (AddTraining.max_participants, "много", "Введите число или «пропустить»"),
])
async def test_invalid_input_keeps_the_step(say, bot, fsm_state, step, bad_input, expected_error):
    await _enter(bot, step, title="T")

    message = await say(bad_input)

    assert expected_error in answered_text(message)
    assert await fsm_state() == f"AddTraining:{step.value}"


async def test_typed_text_is_ignored_while_waiting_for_a_button(say, bot, fsm_state, fsm_data):
    await _enter(bot, AddTraining.day_of_week, title="Йога", training_type="basic")

    message = await say("вторник")

    assert message.handled is False
    assert await fsm_state() == "AddTraining:day_of_week"
    assert (await fsm_data())["title"] == "Йога"      # not overwritten


async def test_cancel_button_discards_the_draft(press, bot, db, fsm_state):
    await _enter(bot, AddTraining.max_participants, title="T")

    event = await press("fsm_cancel")

    assert edited_text(event) == "Отменено."
    assert kb_cmds(edited_keyboard(event)) == ["a:templates"]
    assert await fsm_state() is None
    assert db.added_of(Training) == []


async def test_cancel_command_works_mid_dialog(say, bot, db, fsm_state):
    await _enter(bot, AddTraining.duration, title="T")

    await say("отмена")

    assert await fsm_state() is None
    assert db.added_of(Training) == []


async def test_commands_work_mid_dialog_without_losing_it(
        say, bot, fsm_state, generator, fmt):
    await _enter(bot, AddTraining.start_time, title="T")

    message = await say("расписание")

    assert answered_text(message) == "SCHEDULE_TEXT"
    assert await fsm_state() == "AddTraining:start_time"


async def test_confirm_failure_is_reported_and_dialog_is_closed(
        press, bot, db, fsm_state):
    await _enter(bot, AddTraining.max_participants, title="T", training_type="basic",
                 day_of_week=0, start_time="10:00", duration_minutes=60,
                 max_participants=None)
    db.commit = MagicMock(side_effect=RuntimeError("db is down"))

    event = await press("fsm_confirm")

    assert edited_text(event).startswith("Ошибка:")
    assert await fsm_state() is None
    assert db.closed


async def test_dialog_state_is_per_user(press, say, bot, fsm_state):
    await press("a:tmpl_add", user_id=ADMIN_ID)

    assert await fsm_state(ADMIN_ID) == "AddTraining:title"
    assert await fsm_state(USER_ID) is None
