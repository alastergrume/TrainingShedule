import logging
import random
import re
from datetime import date, timedelta
from typing import Dict, Any, Optional

from vkbottle import API, BaseStateGroup, Callback, GroupEventType, Keyboard, OpenLink
from vkbottle.bot import Bot, Message, MessageEvent
from vkbottle.dispatch.rules.base import ABCRule, StateRule, VBMLRule

from src.config import settings
from src.messengers.interfaces.messenger import MessengerInterface

logger = logging.getLogger(__name__)

RU_DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
TRAINING_TYPES = {
    'personal':   'Персональная',
    'commercial': 'Коммерческая 💸',
    'basic':      'Базовая',
}

# VK обрезает сообщения на 4096; inline-клавиатура — не более 6 рядов и 10 кнопок,
# поэтому страницы меньше, чем в Telegram.
MAX_MSG_LEN = 4000
PER_PAGE_BOOK = 4
PER_PAGE_TEMPLATES = 4
PER_PAGE_BOOKINGS = 3


def _random_id() -> int:
    """VK требует random_id для дедупликации сообщений."""
    return random.getrandbits(31)


# ── Keyboard helpers ──────────────────────────────────────────────────────────

def _kb(*rows: list) -> str:
    kb = Keyboard(inline=True)
    for i, row in enumerate(rows):
        if i:
            kb.row()
        for button in row:
            kb.add(button)
    return kb.get_json()


def _btn(label: str, cmd: str) -> Callback:
    return Callback(label, payload={'cmd': cmd})


def _back(cmd: str = 'a:menu') -> list:
    return [_btn('← Назад', cmd)]


def _admin_kb() -> str:
    return _kb(
        [_btn('📅 Расписание', 'a:schedule')],
        [OpenLink(f"{settings.MINIAPP_URL}/miniapp", label='✏️ Редактор расписания')],
        [_btn('📢 Опубликовать', 'a:publish')],
        [_btn('📋 Шаблоны тренировок', 'a:templates')],
        [_btn('👥 Заявки на запись', 'a:bookings')],
    )


def _week_label(d: date) -> str:
    end = d + timedelta(days=6)
    return f"{d.strftime('%d.%m')}–{end.strftime('%d.%m')}"


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _next_monday() -> date:
    return _this_monday() + timedelta(days=7)


# ── FSM ───────────────────────────────────────────────────────────────────────

class AddTraining(BaseStateGroup):
    title            = 'title'
    training_type    = 'training_type'   # ждём нажатия кнопки
    day_of_week      = 'day_of_week'     # ждём нажатия кнопки
    start_time       = 'start_time'
    duration         = 'duration'
    max_participants = 'max_participants'


# ── Rules ─────────────────────────────────────────────────────────────────────

class PayloadCmd(ABCRule[MessageEvent]):
    """Аналог F.data == / F.data.startswith() из aiogram."""

    def __init__(self, value: str, exact: bool = True):
        self.value = value
        self.exact = exact

    async def check(self, event: MessageEvent) -> bool:
        payload = event.payload or {}
        cmd = payload.get('cmd')
        if not isinstance(cmd, str):
            return False
        return cmd == self.value if self.exact else cmd.startswith(self.value)


def _text(*variants: str) -> VBMLRule:
    # IGNORECASE — команды независимы от регистра
    return VBMLRule(list(variants), flags=re.IGNORECASE | re.DOTALL)


class VKBot(MessengerInterface):
    """VK bot implementation using vkbottle."""

    def __init__(self):
        self.group_token = settings.VK_GROUP_TOKEN
        self.group_id = settings.VK_GROUP_ID

        self.api = API(token=self.group_token)
        self._bot: Optional[Bot] = None

    # ── Admin check ───────────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        ids = settings.VK_ADMIN_IDS
        if isinstance(ids, list):
            return user_id in ids
        return False

    # ── DB helper ─────────────────────────────────────────────────────────────

    def _db(self):
        from src.models.base import SessionLocal
        return SessionLocal()

    # ── MessengerInterface ────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str, **kwargs) -> Any:
        try:
            return await self.api.messages.send(
                peer_id=int(chat_id),
                message=text,
                random_id=_random_id(),
                keyboard=kwargs.get('keyboard'),
                attachment=kwargs.get('attachment'),
            )
        except Exception as e:
            logger.error(f"Failed to send VK message: {e}")
            raise

    async def edit_message(self, chat_id: str, message_id: int, text: str, **kwargs) -> Any:
        try:
            await self.api.messages.edit(
                peer_id=int(chat_id),
                message_id=message_id,
                message=text,
                keyboard=kwargs.get('keyboard'),
            )
            return True
        except Exception as e:
            logger.error(f"Failed to edit VK message: {e}")
            raise

    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        try:
            await self.api.messages.delete(
                message_ids=[message_id],
                delete_for_all=True,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete VK message: {e}")
            return False

    async def send_schedule(self, schedule_data: Dict, **kwargs) -> Dict:
        formatted_text = self._format_schedule(schedule_data)
        try:
            post = await self.api.wall.post(
                owner_id=-self.group_id,
                message=formatted_text,
                from_group=True,
            )
            return {'post_id': post.post_id, 'channel': 'vk', 'group_id': self.group_id}
        except Exception as e:
            logger.error(f"Failed to post to VK wall: {e}")
            message_id = await self.send_message(chat_id=str(self.group_id), text=formatted_text)
            return {'message_id': message_id, 'channel': 'vk', 'chat_id': self.group_id}

    async def update_schedule(self, schedule_data: Dict, post_id: int, **kwargs) -> Dict:
        formatted_text = self._format_schedule(schedule_data)
        try:
            await self.api.wall.edit(
                owner_id=-self.group_id,
                post_id=post_id,
                message=formatted_text,
            )
            return {'post_id': post_id, 'channel': 'vk', 'group_id': self.group_id}
        except Exception as e:
            logger.error(f"Failed to edit VK post: {e}")
            raise

    async def check_post_exists(self, post_id: int) -> bool:
        try:
            result = await self.api.wall.get_by_id(
                posts=[f"-{self.group_id}_{post_id}"],
            )
            return bool(result.items)
        except Exception:
            return False

    async def delete_post(self, post_id: int) -> bool:
        try:
            await self.api.wall.delete(
                owner_id=-self.group_id,
                post_id=post_id,
            )
            return True
        except Exception as e:
            logger.error(f"Failed to delete VK post {post_id}: {e}")
            return False

    async def send_reminder(self, user_id: str, reminder_data: Dict) -> bool:
        try:
            text = self._format_reminder(reminder_data)
            await self.send_message(chat_id=user_id, text=text)
            return True
        except Exception as e:
            logger.error(f"Failed to send VK reminder to {user_id}: {e}")
            return False

    async def get_user_info(self, user_id: str) -> Dict:
        try:
            users = await self.api.users.get(
                user_ids=[user_id],
                fields=['screen_name'],
            )
            if users:
                user = users[0]
                return {
                    'id': user.id,
                    'username': user.screen_name,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }
            return {}
        except Exception as e:
            logger.error(f"Failed to get VK user info for {user_id}: {e}")
            return {}

    def _format_schedule(self, schedule_data: Dict) -> str:
        from src.utils.formatter import ScheduleFormatter
        days = schedule_data.get('days', [])
        if days:
            week_start = days[0].get('date', date.today())
            if isinstance(week_start, str):
                week_start = date.fromisoformat(week_start[:10])
            return ScheduleFormatter.format_week_schedule(days, week_start)
        return "Расписание недоступно"

    def _format_reminder(self, reminder_data: Dict) -> str:
        from src.utils.formatter import ScheduleFormatter
        return ScheduleFormatter.format_reminder(reminder_data)

    # ── FSM helpers ───────────────────────────────────────────────────────────

    async def _fsm_set(self, peer_id: int, state, **values) -> dict:
        peer = await self._bot.state_dispenser.get(peer_id)
        data = dict(peer.payload) if peer and peer.payload else {}
        data.update(values)
        await self._bot.state_dispenser.set(peer_id, state, **data)
        return data

    async def _fsm_data(self, peer_id: int) -> dict:
        peer = await self._bot.state_dispenser.get(peer_id)
        return dict(peer.payload) if peer and peer.payload else {}

    async def _fsm_clear(self, peer_id: int):
        await self._bot.state_dispenser.delete(peer_id)

    # ── Guard for admin callbacks ─────────────────────────────────────────────

    async def _deny(self, event: MessageEvent) -> bool:
        """True — доступа нет, обработку нужно прекратить."""
        if self._is_admin(event.user_id):
            return False
        await event.show_snackbar("Нет доступа")
        return True

    # ── User handlers ─────────────────────────────────────────────────────────

    async def h_start(self, message: Message):
        info = await self.get_user_info(str(message.from_id))
        name = info.get('first_name') or 'друг'
        text = (
            f"Привет, {name}! Я бот для записи на тренировки.\n\n"
            "расписание — расписание на текущую неделю\n"
            "записаться — подать заявку на тренировку"
        )
        if self._is_admin(message.from_id):
            text += "\nадмин — панель администратора"
        await message.answer(text)

    async def h_schedule(self, message: Message):
        db = self._db()
        try:
            from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
            ws = _this_monday()
            days = ScheduleGenerator.generate_from_db(db, ws)
            text = ScheduleFormatter.format_week_schedule(days, ws)
        except Exception as e:
            logger.error(f"Failed to fetch schedule for VK: {e}")
            text = "Не удалось получить расписание."
        finally:
            db.close()
        await message.answer(text[:MAX_MSG_LEN])

    def _available_entries(self, db) -> list:
        """Тренировки, на которые можно записаться (как в Telegram-боте)."""
        from src.utils.formatter import ScheduleGenerator
        from src.models.models import PublishedSchedule

        this_monday = _this_monday()
        published_weeks = (
            db.query(PublishedSchedule.week_start_date)
            .filter(PublishedSchedule.week_start_date >= this_monday)
            .distinct()
            .all()
        )
        week_starts = sorted(set(
            [this_monday] + [
                pw[0].date() if hasattr(pw[0], 'date') else pw[0]
                for pw in published_weeks
            ]
        ))
        out = []
        for ws in week_starts:
            for day in ScheduleGenerator.generate_from_db(db, ws):
                for e in day.get('entries', []):
                    if e['type'] != 'basic' and not e.get('is_cancelled'):
                        d = day['date']
                        label = f"{d.strftime('%d.%m')} {e['time'].split('-')[0]} — {e['title']}"
                        out.append((e['id'], label))
        return out

    def _book_page_kb(self, entries: list, page: int) -> str:
        chunk = entries[page * PER_PAGE_BOOK:(page + 1) * PER_PAGE_BOOK]
        rows = [[_btn(label, f"book:{eid}")] for eid, label in chunk]
        nav = []
        if page > 0:
            nav.append(_btn('‹', f"book_p:{page - 1}"))
        if (page + 1) * PER_PAGE_BOOK < len(entries):
            nav.append(_btn('›', f"book_p:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([_btn('Отмена', 'book:cancel')])
        return _kb(*rows)

    async def h_book(self, message: Message):
        db = self._db()
        try:
            entries = self._available_entries(db)
            if not entries:
                await message.answer("Нет доступных тренировок для записи.")
                return
            await message.answer(
                "Выберите тренировку для записи:",
                keyboard=self._book_page_kb(entries, 0),
            )
        except Exception as e:
            logger.error(f"VK book list failed: {e}")
            await message.answer("Ошибка.")
        finally:
            db.close()

    async def cb_book_page(self, event: MessageEvent):
        await event.send_empty_answer()
        page = int(event.payload['cmd'].split(':')[1])
        db = self._db()
        try:
            entries = self._available_entries(db)
            await event.edit_message(
                message="Выберите тренировку для записи:",
                keyboard=self._book_page_kb(entries, page),
            )
        except Exception as e:
            logger.error(f"VK book page failed: {e}")
        finally:
            db.close()

    async def cb_book(self, event: MessageEvent):
        await event.send_empty_answer()
        cmd = event.payload['cmd']
        if cmd == 'book:cancel':
            await event.edit_message(message="Запись отменена.")
            return

        entry_id = int(cmd.split(':')[1])
        db = self._db()
        try:
            from src.models.models import ScheduleEntry, Booking, User
            from src.models.enums import BookingStatus

            entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
            if not entry:
                await event.edit_message(message="Тренировка не найдена.")
                return

            # Найти или создать пользователя — здесь заполняется User.vk_id
            user = db.query(User).filter(User.vk_id == event.user_id).first()
            if not user:
                info = await self.get_user_info(str(event.user_id))
                user = User(
                    vk_id=event.user_id,
                    username=info.get('username'),
                    first_name=info.get('first_name') or '',
                    last_name=info.get('last_name'),
                )
                db.add(user); db.commit(); db.refresh(user)

            existing = db.query(Booking).filter(
                Booking.user_id == user.id,
                Booking.schedule_entry_id == entry_id,
                Booking.status != BookingStatus.CANCELLED,
            ).first()
            if existing:
                await event.edit_message(message="Вы уже подали заявку на эту тренировку.")
                return

            booking = Booking(
                user_id=user.id,
                training_id=entry.training_id,
                schedule_entry_id=entry_id,
                status=BookingStatus.PENDING,
            )
            db.add(booking); db.commit(); db.refresh(booking)

            await event.edit_message(
                message=(
                    f"✅ Заявка принята! Ожидайте подтверждения от администратора.\n"
                    f"Тренировка: {entry.training.title}\n"
                    f"Дата: {entry.date.strftime('%d.%m.%Y')} в {entry.start_time}"
                )
            )

            notif = (
                f"📋 Новая заявка!\n"
                f"👤 {user.first_name} {user.last_name or ''}\n"
                f"🏋️ {entry.training.title}\n"
                f"📅 {entry.date.strftime('%d.%m.%Y')} в {entry.start_time}\n\n"
                f"Подтвердить: админ"
            )
            for aid in (settings.VK_ADMIN_IDS or []):
                try:
                    await self.send_message(str(aid), notif)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"VK booking failed: {e}")
            await event.edit_message(message="Ошибка при записи.")
        finally:
            db.close()

    async def h_cancel(self, message: Message):
        await self._fsm_clear(message.peer_id)
        await message.answer("Отменено. Напишите «админ», чтобы вернуться в меню.")

    # ── Admin: menu ───────────────────────────────────────────────────────────

    async def h_admin(self, message: Message):
        if not self._is_admin(message.from_id):
            await message.answer("У вас нет прав администратора.")
            return
        await message.answer("Панель администратора:", keyboard=_admin_kb())

    async def cb_menu(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        await event.edit_message(message="Панель администратора:", keyboard=_admin_kb())

    # ── Admin: schedule ───────────────────────────────────────────────────────

    async def cb_schedule(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        cw, nw = _this_monday(), _next_monday()
        await event.edit_message(
            message="Выберите неделю для генерации расписания:",
            keyboard=_kb(
                [_btn(f"📅 Текущая неделя ({_week_label(cw)})", f"a:gen:{cw.isoformat()}")],
                [_btn(f"📅 Следующая неделя ({_week_label(nw)})", f"a:gen:{nw.isoformat()}")],
                _back(),
            ),
        )

    async def cb_generate(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        ws = date.fromisoformat(event.payload['cmd'].split(':', 2)[2])
        db = self._db()
        try:
            from src.business_logic.services.schedule_service import ScheduleService
            entries = ScheduleService(db).generate_weekly_schedule(ws)
            await event.edit_message(
                message=f"✅ Сгенерировано {len(entries)} занятий на неделю {_week_label(ws)}.",
                keyboard=_kb(
                    [_btn("📢 Опубликовать эту неделю", f"a:pub:{ws.isoformat()}")],
                    _back('a:schedule'),
                ),
            )
        except Exception as e:
            logger.error(f"VK generate failed: {e}")
            await event.edit_message(
                message=f"Ошибка: {e}",
                keyboard=_kb(_back('a:schedule')),
            )
        finally:
            db.close()

    # ── Admin: publish ────────────────────────────────────────────────────────

    async def cb_publish_menu(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        cw, nw = _this_monday(), _next_monday()
        await event.edit_message(
            message="Выберите неделю для публикации:",
            keyboard=_kb(
                [_btn(f"Текущая неделя ({_week_label(cw)})", f"a:pub:{cw.isoformat()}")],
                [_btn(f"Следующая неделя ({_week_label(nw)})", f"a:pub:{nw.isoformat()}")],
                _back(),
            ),
        )

    async def cb_publish(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        ws = date.fromisoformat(event.payload['cmd'].split(':', 2)[2])
        db = self._db()
        try:
            from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
            days = ScheduleGenerator.generate_from_db(db, ws)
            preview = ScheduleFormatter.format_week_schedule(days, ws)
            text = f"Превью расписания {_week_label(ws)}:\n\n{preview}"
            if len(text) > MAX_MSG_LEN:
                text = text[:MAX_MSG_LEN - 10] + "\n..."
            await event.edit_message(
                message=text,
                keyboard=_kb(
                    [_btn("✅ Опубликовать", f"a:pub_ok:{ws.isoformat()}")],
                    _back('a:publish'),
                ),
            )
        except Exception as e:
            logger.error(f"VK publish preview failed: {e}")
            await event.edit_message(message=f"Ошибка: {e}", keyboard=_kb(_back('a:publish')))
        finally:
            db.close()

    async def cb_publish_confirm(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        ws = date.fromisoformat(event.payload['cmd'].split(':', 2)[2])
        db = self._db()
        try:
            from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
            from src.business_logic.services.schedule_service import ScheduleService
            from src.celery_app import publish_schedule_to_channels

            days = ScheduleGenerator.generate_from_db(db, ws)
            content = ScheduleFormatter.format_week_schedule(days, ws)
            ScheduleService(db).publish_schedule(ws, content)

            publish_schedule_to_channels.delay(
                ws.isoformat(),
                {"days": [
                    {**d, "date": d["date"].isoformat()
                           if hasattr(d["date"], "isoformat") else str(d["date"])}
                    for d in days
                ]},
            )
            await event.edit_message(
                message=f"📢 Расписание на {_week_label(ws)} опубликовано!",
                keyboard=_kb(_back()),
            )
        except Exception as e:
            logger.error(f"VK publish failed: {e}")
            await event.edit_message(message=f"Ошибка публикации: {e}", keyboard=_kb(_back()))
        finally:
            db.close()

    # ── Admin: templates ──────────────────────────────────────────────────────

    async def cb_templates(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        parts = event.payload['cmd'].split(':')
        page = int(parts[2]) if len(parts) == 3 else 0
        db = self._db()
        try:
            from src.models.models import Training
            all_t = (
                db.query(Training).filter(Training.is_active == True)
                .order_by(Training.day_of_week, Training.start_time).all()
            )
            chunk = all_t[page * PER_PAGE_TEMPLATES:(page + 1) * PER_PAGE_TEMPLATES]
            rows = [
                [_btn(f"{RU_DAYS[t.day_of_week][:2]} {t.start_time} — {t.title}", f"a:tmpl:{t.id}")]
                for t in chunk
            ]
            nav = []
            if page > 0:
                nav.append(_btn("‹", f"a:templates:{page - 1}"))
            if (page + 1) * PER_PAGE_TEMPLATES < len(all_t):
                nav.append(_btn("›", f"a:templates:{page + 1}"))
            nav.append(_btn("➕ Добавить", 'a:tmpl_add'))
            rows.append(nav)
            rows.append(_back())
            await event.edit_message(
                message=f"📋 Шаблоны тренировок ({len(all_t)}):",
                keyboard=_kb(*rows),
            )
        except Exception as e:
            logger.error(f"VK templates failed: {e}")
            await event.edit_message(message=f"Ошибка: {e}", keyboard=_kb(_back()))
        finally:
            db.close()

    async def cb_template_detail(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        tid = int(event.payload['cmd'].split(':')[2])
        db = self._db()
        try:
            from src.models.models import Training
            t = db.query(Training).filter(Training.id == tid).first()
            if not t:
                await event.show_snackbar("Не найдено")
                return
            await event.edit_message(
                message=(
                    f"{t.title}\n"
                    f"Тип: {TRAINING_TYPES.get(t.training_type.value, t.training_type.value)}\n"
                    f"День: {RU_DAYS[t.day_of_week]}\n"
                    f"Время: {t.start_time}, {t.duration_minutes} мин.\n"
                    f"Макс. участников: {t.max_participants or 'без ограничений'}\n"
                    f"Описание: {t.description or '—'}"
                ),
                keyboard=_kb(
                    [_btn("🗑 Удалить", f"a:tmpl_del:{tid}")],
                    _back('a:templates'),
                ),
            )
        except Exception as e:
            logger.error(f"VK template detail failed: {e}")
        finally:
            db.close()

    async def cb_template_delete(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        tid = int(event.payload['cmd'].split(':')[2])
        await event.edit_message(
            message="Удалить этот шаблон?",
            keyboard=_kb(
                [_btn("✅ Да, удалить", f"a:tmpl_del_ok:{tid}")],
                _back('a:templates'),
            ),
        )

    async def cb_template_delete_ok(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        tid = int(event.payload['cmd'].split(':')[2])
        db = self._db()
        try:
            from src.models.models import Training
            t = db.query(Training).filter(Training.id == tid).first()
            if t:
                t.is_active = False
                db.commit()
            await event.edit_message(
                message="✅ Шаблон удалён.",
                keyboard=_kb(_back('a:templates')),
            )
        except Exception as e:
            logger.error(f"VK template delete failed: {e}")
        finally:
            db.close()

    # ── FSM: add training template ────────────────────────────────────────────

    async def cb_tmpl_add_start(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        await self._fsm_set(event.peer_id, AddTraining.title)
        await event.edit_message(
            message="Введите название тренировки:\n(или «отмена» для отмены)"
        )

    async def fsm_title(self, message: Message):
        await self._fsm_set(message.peer_id, AddTraining.training_type,
                            title=message.text.strip())
        await message.answer(
            "Выберите тип тренировки:",
            keyboard=_kb(
                [_btn('Персональная', 'fsm_type:personal')],
                [_btn('Коммерческая 💸', 'fsm_type:commercial')],
                [_btn('Базовая', 'fsm_type:basic')],
            ),
        )

    async def cb_fsm_type(self, event: MessageEvent):
        await event.send_empty_answer()
        await self._fsm_set(
            event.peer_id, AddTraining.day_of_week,
            training_type=event.payload['cmd'].split(':')[1],
        )
        await event.edit_message(
            message="Выберите день недели:",
            keyboard=_kb(
                [_btn('Пн', 'fsm_day:0'), _btn('Вт', 'fsm_day:1'), _btn('Ср', 'fsm_day:2')],
                [_btn('Чт', 'fsm_day:3'), _btn('Пт', 'fsm_day:4')],
                [_btn('Сб', 'fsm_day:5'), _btn('Вс', 'fsm_day:6')],
            ),
        )

    async def cb_fsm_day(self, event: MessageEvent):
        await event.send_empty_answer()
        await self._fsm_set(
            event.peer_id, AddTraining.start_time,
            day_of_week=int(event.payload['cmd'].split(':')[1]),
        )
        await event.edit_message(message="Введите время начала (ЧЧ:ММ), например: 19:30")

    async def fsm_time(self, message: Message):
        text = message.text.strip()
        if not re.match(r'^\d{1,2}:\d{2}$', text):
            await message.answer("Формат: ЧЧ:ММ, например 09:00")
            return
        await self._fsm_set(message.peer_id, AddTraining.duration, start_time=text)
        await message.answer("Введите продолжительность в минутах (например: 60):")

    async def fsm_duration(self, message: Message):
        text = message.text.strip()
        if not text.isdigit():
            await message.answer("Введите число минут, например: 60")
            return
        await self._fsm_set(message.peer_id, AddTraining.max_participants,
                            duration_minutes=int(text))
        await message.answer(
            "Максимальное количество участников?\n"
            "(введите число или «пропустить» для неограниченного)"
        )

    async def fsm_max(self, message: Message):
        text = message.text.strip()
        max_p = None
        if text.lower() != 'пропустить':
            if not text.isdigit():
                await message.answer("Введите число или «пропустить»")
                return
            max_p = int(text)
        data = await self._fsm_set(message.peer_id, AddTraining.max_participants,
                                   max_participants=max_p)
        await message.answer(
            "Проверьте данные:\n"
            f"Название: {data['title']}\n"
            f"Тип: {TRAINING_TYPES.get(data['training_type'], data['training_type'])}\n"
            f"День: {RU_DAYS[data['day_of_week']]}\n"
            f"Время: {data['start_time']}, {data['duration_minutes']} мин.\n"
            f"Макс. участников: {max_p or 'без ограничений'}",
            keyboard=_kb(
                [_btn('✅ Сохранить', 'fsm_confirm'), _btn('❌ Отмена', 'fsm_cancel')],
            ),
        )

    async def cb_fsm_confirm(self, event: MessageEvent):
        await event.send_empty_answer()
        data = await self._fsm_data(event.peer_id)
        await self._fsm_clear(event.peer_id)
        db = self._db()
        try:
            from src.models.models import Training
            from src.models.enums import TrainingType
            t = Training(
                title=data['title'],
                training_type=TrainingType(data['training_type']),
                day_of_week=data['day_of_week'],
                start_time=data['start_time'],
                duration_minutes=data['duration_minutes'],
                max_participants=data.get('max_participants'),
                is_active=True,
            )
            db.add(t); db.commit()
            await event.edit_message(
                message=f"✅ Шаблон «{t.title}» добавлен!",
                keyboard=_kb(_back('a:templates')),
            )
        except Exception as e:
            logger.error(f"VK add template failed: {e}")
            await event.edit_message(message=f"Ошибка: {e}", keyboard=_kb(_back('a:templates')))
        finally:
            db.close()

    async def cb_fsm_cancel(self, event: MessageEvent):
        await event.send_empty_answer()
        await self._fsm_clear(event.peer_id)
        await event.edit_message(message="Отменено.", keyboard=_kb(_back('a:templates')))

    # ── Admin: bookings ───────────────────────────────────────────────────────

    async def cb_bookings(self, event: MessageEvent):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        parts = event.payload['cmd'].split(':')
        page = int(parts[2]) if len(parts) == 3 else 0
        db = self._db()
        try:
            from src.models.models import Booking, ScheduleEntry, User
            from src.models.enums import BookingStatus
            all_b = (
                db.query(Booking)
                .filter(Booking.status == BookingStatus.PENDING)
                .order_by(Booking.created_at)
                .all()
            )
            if not all_b:
                await event.edit_message(
                    message="👥 Нет заявок, требующих подтверждения.",
                    keyboard=_kb(_back()),
                )
                return

            chunk = all_b[page * PER_PAGE_BOOKINGS:(page + 1) * PER_PAGE_BOOKINGS]
            rows = []
            for b in chunk:
                user = db.query(User).filter(User.id == b.user_id).first()
                entry = db.query(ScheduleEntry).filter(
                    ScheduleEntry.id == b.schedule_entry_id
                ).first()
                uname = f"{user.first_name} {user.last_name or ''}".strip() if user else "?"
                t_name = entry.training.title if entry else "?"
                t_date = entry.date.strftime('%d.%m %H:%M') if entry else "?"
                rows.append([
                    _btn(f"✅ {uname} / {t_name} {t_date}", f"a:book_ok:{b.id}"),
                    _btn("❌", f"a:book_no:{b.id}"),
                ])

            nav = []
            if page > 0:
                nav.append(_btn("‹", f"a:bookings:{page - 1}"))
            if (page + 1) * PER_PAGE_BOOKINGS < len(all_b):
                nav.append(_btn("›", f"a:bookings:{page + 1}"))
            if nav:
                rows.append(nav)
            rows.append(_back())

            await event.edit_message(
                message=f"👥 Заявки на подтверждение ({len(all_b)}):",
                keyboard=_kb(*rows),
            )
        except Exception as e:
            logger.error(f"VK bookings failed: {e}")
            await event.edit_message(message=f"Ошибка: {e}", keyboard=_kb(_back()))
        finally:
            db.close()

    def _resolve_booking(self, db, bid: int, confirmed: bool):
        """Меняет статус заявки; возвращает (заявка, (vk_id, текст уведомления))."""
        from src.models.models import Booking, User, ScheduleEntry
        from src.models.enums import BookingStatus

        b = db.query(Booking).filter(Booking.id == bid).first()
        if not b:
            return None, None
        b.status = BookingStatus.CONFIRMED if confirmed else BookingStatus.CANCELLED
        if not confirmed:
            b.notes = "Отклонено администратором"
        db.commit()

        user = db.query(User).filter(User.id == b.user_id).first()
        entry = db.query(ScheduleEntry).filter(
            ScheduleEntry.id == b.schedule_entry_id
        ).first()
        if not (user and user.vk_id and entry):
            return b, None
        if confirmed:
            text = (
                f"✅ Ваша запись подтверждена!\n"
                f"🏋️ {entry.training.title}\n"
                f"📅 {entry.date.strftime('%d.%m.%Y')} в {entry.start_time}"
            )
        else:
            text = (
                f"❌ К сожалению, ваша запись на тренировку отклонена.\n"
                f"🏋️ {entry.training.title}\n"
                f"По вопросам обратитесь к администратору."
            )
        return b, (user.vk_id, text)

    async def _booking_decision(self, event: MessageEvent, confirmed: bool):
        if await self._deny(event):
            return
        await event.send_empty_answer()
        bid = int(event.payload['cmd'].split(':')[2])
        db = self._db()
        try:
            b, notify = self._resolve_booking(db, bid, confirmed)
            if not b:
                await event.show_snackbar("Заявка не найдена")
                return
            if notify:
                try:
                    await self.send_message(str(notify[0]), notify[1])
                except Exception:
                    pass
            verb = "подтверждена" if confirmed else "отклонена"
            mark = "✅" if confirmed else "❌"
            await event.edit_message(
                message=f"{mark} Заявка #{bid} {verb}.",
                keyboard=_kb([_btn("← К заявкам", 'a:bookings')]),
            )
        except Exception as e:
            logger.error(f"VK booking decision failed: {e}")
            await event.edit_message(message=f"Ошибка: {e}")
        finally:
            db.close()

    async def cb_booking_confirm(self, event: MessageEvent):
        await self._booking_decision(event, confirmed=True)

    async def cb_booking_reject(self, event: MessageEvent):
        await self._booking_decision(event, confirmed=False)

    # ── Wiring ────────────────────────────────────────────────────────────────

    def _build_bot(self) -> Bot:
        bot = Bot(api=self.api)
        self._bot = bot

        # Команды — раньше FSM, чтобы работали и внутри диалога (как в Telegram)
        bot.on.message(_text("начать", "/start"))(self.h_start)
        bot.on.message(_text("расписание", "/schedule"))(self.h_schedule)
        bot.on.message(_text("записаться", "/book"))(self.h_book)
        bot.on.message(_text("админ", "/admin"))(self.h_admin)
        bot.on.message(_text("отмена", "/cancel"))(self.h_cancel)

        # FSM-шаги (текстовый ввод)
        bot.on.message(StateRule(AddTraining.title))(self.fsm_title)
        bot.on.message(StateRule(AddTraining.start_time))(self.fsm_time)
        bot.on.message(StateRule(AddTraining.duration))(self.fsm_duration)
        bot.on.message(StateRule(AddTraining.max_participants))(self.fsm_max)

        # Нажатия inline-кнопок. Порядок важен: длинные префиксы раньше коротких.
        ev = GroupEventType.MESSAGE_EVENT
        routes = [
            (PayloadCmd('book_p:', exact=False),        self.cb_book_page),
            (PayloadCmd('book:', exact=False),          self.cb_book),
            (PayloadCmd('a:menu'),                      self.cb_menu),
            (PayloadCmd('a:schedule'),                  self.cb_schedule),
            (PayloadCmd('a:gen:', exact=False),         self.cb_generate),
            (PayloadCmd('a:publish'),                   self.cb_publish_menu),
            (PayloadCmd('a:pub_ok:', exact=False),      self.cb_publish_confirm),
            (PayloadCmd('a:pub:', exact=False),         self.cb_publish),
            (PayloadCmd('a:templates', exact=False),    self.cb_templates),
            (PayloadCmd('a:tmpl_add'),                  self.cb_tmpl_add_start),
            (PayloadCmd('a:tmpl_del_ok:', exact=False), self.cb_template_delete_ok),
            (PayloadCmd('a:tmpl_del:', exact=False),    self.cb_template_delete),
            (PayloadCmd('a:tmpl:', exact=False),        self.cb_template_detail),
            (PayloadCmd('a:bookings', exact=False),     self.cb_bookings),
            (PayloadCmd('a:book_ok:', exact=False),     self.cb_booking_confirm),
            (PayloadCmd('a:book_no:', exact=False),     self.cb_booking_reject),
            (PayloadCmd('fsm_type:', exact=False),      self.cb_fsm_type),
            (PayloadCmd('fsm_day:', exact=False),       self.cb_fsm_day),
            (PayloadCmd('fsm_confirm'),                 self.cb_fsm_confirm),
            (PayloadCmd('fsm_cancel'),                  self.cb_fsm_cancel),
        ]
        for rule, handler in routes:
            bot.on.raw_event(ev, MessageEvent, rule)(handler)

        return bot

    async def run(self):
        logger.info("Starting VK bot...")
        if self._bot is None:
            self._build_bot()
        await self._bot.run_polling()


# Register with factory
from src.messengers.interfaces.messenger import MessengerFactory
MessengerFactory.register("vk", VKBot)
