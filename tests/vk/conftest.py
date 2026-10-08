"""Fixtures for the VK bot tests.

Everything external is mocked: the database (FakeSession), the VK API, Celery,
the service layer and the formatter. Routing, FSM storage and the handlers
themselves are the real code, so a "press" or a "say" goes through the same
rules vkbottle would apply.
"""
import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from vkbottle import GroupEventType
from vkbottle.dispatch.rules.base import get_state_repr

from src.config import settings
from tests.fakes import FakeSession, make_event, make_message
from tests.vk import ADMIN_ID, USER_ID


def _fake_api():
    api = MagicMock(name="vk_api")
    api.messages.send = AsyncMock(return_value=1)
    api.messages.edit = AsyncMock(return_value=1)
    api.messages.delete = AsyncMock(return_value=[])
    api.wall.post = AsyncMock(return_value=SimpleNamespace(post_id=77))
    api.wall.edit = AsyncMock(return_value=1)
    api.wall.delete = AsyncMock(return_value=1)
    api.wall.get_by_id = AsyncMock(return_value=SimpleNamespace(items=[object()]))
    api.users.get = AsyncMock(return_value=[SimpleNamespace(
        id=USER_ID, first_name="Иван", last_name="Петров", screen_name="ivan",
    )])
    return api


async def _passes(rules, event) -> bool:
    for rule in rules:
        result = await rule.check(event)
        if result is False or result is None:
            return False
    return True


@pytest.fixture
def db():
    return FakeSession()


@pytest.fixture
def bot(monkeypatch, db):
    """A VKBot wired exactly as in production, with the VK API and DB mocked."""
    monkeypatch.setattr(settings, "VK_GROUP_TOKEN", "test-token")
    monkeypatch.setattr(settings, "VK_GROUP_ID", 555)
    monkeypatch.setattr(settings, "VK_ADMIN_IDS", [ADMIN_ID])
    monkeypatch.setattr(settings, "MINIAPP_URL", "https://example.test")

    from src.messengers.vk.bot import VKBot
    b = VKBot()
    b._build_bot()
    b.api = _fake_api()
    monkeypatch.setattr(b, "_db", lambda: db)
    return b


# ── Driving the bot through its real routing ─────────────────────────────────

@pytest.fixture
def find_callback(bot):
    """Handler a button with this payload would reach, or None."""
    async def _find(cmd):
        event = make_event(cmd)
        views = bot._bot.labeler.raw_event_view.handlers[GroupEventType.MESSAGE_EVENT]
        for basement in views:
            if await _passes(basement.handler.rules, event):
                return basement.handler.handler
        return None
    return _find


@pytest.fixture
def find_message(bot):
    """Handler a text would reach in the given FSM state, or None."""
    async def _find(text, state=None):
        state_peer = None
        if state is not None:
            state_peer = SimpleNamespace(state=get_state_repr(state), payload={})
        message = make_message(text, state_peer=state_peer)
        for handler in bot._bot.labeler.message_view.handlers:
            if await _passes(handler.rules, message):
                return handler.handler
        return None
    return _find


@pytest.fixture
def press(bot, find_callback):
    """Press an inline button. Returns the event so tests can inspect replies."""
    async def _press(cmd, user_id=ADMIN_ID):
        handler = await find_callback(cmd)
        assert handler is not None, f"no handler routes payload {cmd!r}"
        event = make_event(cmd, user_id=user_id)
        await handler(event)
        return event
    return _press


@pytest.fixture
def say(bot):
    """Send a text message; FSM state comes from the bot's real storage."""
    async def _say(text, from_id=ADMIN_ID):
        state_peer = await bot._bot.state_dispenser.get(from_id)
        message = make_message(text, from_id=from_id, state_peer=state_peer)
        message.handled = False
        for handler in bot._bot.labeler.message_view.handlers:
            if await _passes(handler.rules, message):
                await handler.handler(message)
                message.handled = True
                break
        return message
    return _say


@pytest.fixture
def fsm_state(bot):
    """Current FSM state name of a peer, or None."""
    async def _state(peer_id=ADMIN_ID):
        peer = await bot._bot.state_dispenser.get(peer_id)
        return peer.state if peer else None
    return _state


@pytest.fixture
def fsm_data(bot):
    async def _data(peer_id=ADMIN_ID):
        peer = await bot._bot.state_dispenser.get(peer_id)
        return dict(peer.payload) if peer else {}
    return _data


# ── Mocked collaborators ─────────────────────────────────────────────────────

@pytest.fixture
def generator(monkeypatch):
    """ScheduleGenerator.generate_from_db: set .days or .error, read .calls."""
    from src.utils.formatter import ScheduleGenerator
    g = SimpleNamespace(days=[], calls=[], error=None)

    def fake(db_session, week_start):
        g.calls.append(week_start)
        if g.error:
            raise g.error
        return g.days

    monkeypatch.setattr(ScheduleGenerator, "generate_from_db", staticmethod(fake))
    return g


@pytest.fixture
def fmt(monkeypatch):
    """ScheduleFormatter with a controllable week text."""
    from src.utils.formatter import ScheduleFormatter
    f = SimpleNamespace(week_text="SCHEDULE_TEXT", week_calls=[])

    def fake_week(days, week_start):
        f.week_calls.append((days, week_start))
        return f.week_text

    monkeypatch.setattr(ScheduleFormatter, "format_week_schedule", staticmethod(fake_week))
    monkeypatch.setattr(ScheduleFormatter, "format_reminder",
                        staticmethod(lambda data: "REMINDER_TEXT"))
    return f


@pytest.fixture
def schedule_service(monkeypatch):
    """Replaces ScheduleService with a mock class (instance: .return_value)."""
    import src.business_logic.services.schedule_service as module
    service_cls = MagicMock(name="ScheduleService")
    service_cls.return_value.generate_weekly_schedule.return_value = [1, 2, 3]
    monkeypatch.setattr(module, "ScheduleService", service_cls)
    return service_cls


@pytest.fixture
def celery(monkeypatch):
    """Stub for src.celery_app so publishing never touches a broker.

    Returns the mocked publish_schedule_to_channels task.
    """
    module = types.ModuleType("src.celery_app")
    module.publish_schedule_to_channels = MagicMock(name="publish_schedule_to_channels")
    monkeypatch.setitem(sys.modules, "src.celery_app", module)
    return module.publish_schedule_to_channels
