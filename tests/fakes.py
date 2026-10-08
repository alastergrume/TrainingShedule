"""Test doubles shared by the bot tests. No database, no network.

FakeSession stands in for a SQLAlchemy session: it hands back the rows a test
registered for a model and records what the code under test adds/commits.
It does NOT evaluate filters, so tests verify handler logic, not SQL.
"""
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from src.models.enums import BookingStatus, TrainingType
from src.models.models import Booking, ScheduleEntry, Training, User


class FakeQuery:
    """Chainable query that returns the rows it was built with."""

    def __init__(self, rows):
        self._rows = list(rows)

    def _chain(self, *args, **kwargs):
        return self

    filter = filter_by = join = order_by = distinct = limit = offset = _chain

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def count(self):
        return len(self._rows)


class FakeSession:
    def __init__(self):
        self._rows = {}
        self.added = []
        self.commits = 0
        self.closed = False
        self._next_id = 100

    def given(self, model, *rows):
        """Rows returned by db.query(model) (or db.query(model.column))."""
        self._rows[model] = list(rows)
        return self

    def query(self, *entities):
        entity = entities[0]
        model = getattr(entity, "class_", entity)  # Model.column -> Model
        return FakeQuery(self._rows.get(model, []))

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        if getattr(obj, "id", "unset") is None:
            obj.id = self._next_id
            self._next_id += 1

    def close(self):
        self.closed = True

    def added_of(self, model):
        return [o for o in self.added if isinstance(o, model)]


# ── VK events / messages ─────────────────────────────────────────────────────

def make_event(cmd, user_id=1, peer_id=None):
    """Stand-in for vkbottle MessageEvent (an inline-button press)."""
    return SimpleNamespace(
        payload={"cmd": cmd},
        user_id=user_id,
        peer_id=peer_id or user_id,
        edit_message=AsyncMock(),
        send_empty_answer=AsyncMock(),
        show_snackbar=AsyncMock(),
    )


def make_message(text, from_id=1, peer_id=None, state_peer=None):
    """Stand-in for vkbottle Message (a text message)."""
    return SimpleNamespace(
        text=text,
        from_id=from_id,
        peer_id=peer_id or from_id,
        state_peer=state_peer,
        answer=AsyncMock(),
    )


def edited_text(event):
    return event.edit_message.await_args.kwargs["message"]


def edited_keyboard(event):
    return event.edit_message.await_args.kwargs.get("keyboard")


def answered_text(message):
    return message.answer.await_args.args[0]


def answered_keyboard(message):
    return message.answer.await_args.kwargs.get("keyboard")


# ── Keyboard inspection ──────────────────────────────────────────────────────

def kb_buttons(keyboard_json):
    """Flat list of button 'action' dicts."""
    return [b["action"] for row in json.loads(keyboard_json)["buttons"] for b in row]


def kb_cmds(keyboard_json):
    """Callback commands of every button, in order."""
    return [
        a["payload"]["cmd"] for a in kb_buttons(keyboard_json)
        if isinstance(a.get("payload"), dict) and "cmd" in a["payload"]
    ]


def kb_labels(keyboard_json):
    return [a["label"] for a in kb_buttons(keyboard_json)]


def assert_vk_limits(keyboard_json):
    """VK inline keyboards: at most 6 rows and 10 buttons."""
    rows = json.loads(keyboard_json)["buttons"]
    total = sum(len(r) for r in rows)
    assert len(rows) <= 6, f"{len(rows)} rows > 6"
    assert total <= 10, f"{total} buttons > 10"


# ── Domain builders ──────────────────────────────────────────────────────────

def make_training(id=1, title="Йога", type_=TrainingType.PERSONAL, day=0,
                  start="19:00", duration=60, max_participants=None,
                  description=None, is_active=True):
    return Training(
        id=id, title=title, training_type=type_, day_of_week=day,
        start_time=start, duration_minutes=duration,
        max_participants=max_participants, description=description,
        is_active=is_active,
    )


def make_entry(id=5, training=None, when=datetime(2026, 10, 14, 19, 0),
               start="19:00", end="20:00"):
    entry = ScheduleEntry(id=id, training_id=(training.id if training else 1),
                          date=when, start_time=start, end_time=end)
    entry.training = training or make_training()
    return entry


def make_user(id=7, vk_id=None, first_name="Анна", last_name="Смирнова"):
    return User(id=id, vk_id=vk_id, first_name=first_name, last_name=last_name)


def make_booking(id=1, user_id=7, training_id=1, entry_id=5,
                 status=BookingStatus.PENDING):
    return Booking(id=id, user_id=user_id, training_id=training_id,
                   schedule_entry_id=entry_id, status=status)


def day(date_, *entries):
    """One day of ScheduleGenerator.generate_from_db output."""
    return {"date": date_, "entries": list(entries)}


def gen_entry(id, title="Йога", type_="personal", time="19:00-20:00",
              is_cancelled=False):
    """One entry of ScheduleGenerator.generate_from_db output."""
    return {"id": id, "title": title, "type": type_, "time": time,
            "is_cancelled": is_cancelled, "bookings": []}
