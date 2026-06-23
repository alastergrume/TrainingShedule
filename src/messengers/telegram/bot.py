import asyncio
import logging
from datetime import date, timedelta
from typing import Dict, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo,
)

from src.config import settings
from src.messengers.interfaces.messenger import MessengerInterface

logger = logging.getLogger(__name__)

RU_DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
TRAINING_TYPES = {
    'personal':   'Персональная',
    'commercial': 'Коммерческая 💸',
    'basic':      'Базовая',
}


# ── FSM states ────────────────────────────────────────────────────────────────

class AddTraining(StatesGroup):
    title           = State()
    training_type   = State()
    day_of_week     = State()
    start_time      = State()
    duration        = State()
    max_participants = State()


# ── Keyboard helpers ──────────────────────────────────────────────────────────

def _kb(*rows: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))

def _btn(text: str, data: str = None, web_app: WebAppInfo = None) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, web_app=web_app)

def _back(data: str = 'a:menu') -> list:
    return [_btn('← Назад', data)]


def _admin_kb() -> InlineKeyboardMarkup:
    miniapp_url = f"{settings.MINIAPP_URL}/miniapp"
    return _kb(
        [_btn('📅 Расписание',            'a:schedule')],
        [_btn('✏️ Редактор расписания',   web_app=WebAppInfo(url=miniapp_url))],
        [_btn('📢 Опубликовать',           'a:publish')],
        [_btn('📋 Шаблоны тренировок',    'a:templates')],
        [_btn('👥 Заявки на запись',       'a:bookings')],
    )


def _week_label(d: date) -> str:
    end = d + timedelta(days=6)
    return f"{d.strftime('%d.%m')}–{end.strftime('%d.%m')}"


def _this_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def _next_monday() -> date:
    return _this_monday() + timedelta(days=7)


# ── Bot class ─────────────────────────────────────────────────────────────────

class TelegramBot(MessengerInterface):

    def __init__(self):
        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        self.dp  = Dispatcher(storage=MemoryStorage())
        self.channel_id = settings.TELEGRAM_CHANNEL_ID
        self._register_handlers()

    # ── Admin check ───────────────────────────────────────────────────────────

    def _is_admin(self, user_id: int) -> bool:
        ids = settings.TELEGRAM_ADMIN_IDS
        if isinstance(ids, list):
            return user_id in ids
        return False

    # ── DB helper ─────────────────────────────────────────────────────────────

    def _db(self):
        from src.models.base import SessionLocal
        return SessionLocal()

    # ── MessengerInterface ────────────────────────────────────────────────────

    async def send_message(self, chat_id: str, text: str, **kw) -> Any:
        try:
            message_kwargs = {
                'chat_id': chat_id,
                'text': text,
                'reply_markup': kw.get('reply_markup'),
                'disable_web_page_preview': kw.get('disable_web_page_preview', True),
            }
            if kw.get('parse_mode') is not None:
                message_kwargs['parse_mode'] = kw['parse_mode']
            msg = await self.bot.send_message(
                **message_kwargs,
            )
            return msg.message_id
        except Exception as e:
            logger.error(f"send_message error: {e}"); raise

    async def edit_message(self, chat_id: str, message_id: int, text: str, **kw) -> Any:
        try:
            message_kwargs = {
                'chat_id': chat_id,
                'message_id': message_id,
                'text': text,
                'reply_markup': kw.get('reply_markup'),
                'disable_web_page_preview': kw.get('disable_web_page_preview', True),
            }
            if kw.get('parse_mode') is not None:
                message_kwargs['parse_mode'] = kw['parse_mode']
            await self.bot.edit_message_text(
                **message_kwargs,
            )
            return True
        except Exception as e:
            logger.error(f"edit_message error: {e}"); raise

    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except Exception as e:
            logger.error(f"delete_message error: {e}"); return False

    async def send_schedule(self, schedule_data: Dict, **kw) -> Dict:
        text = self._fmt_schedule(schedule_data)
        mid  = await self.send_message(chat_id=self.channel_id, text=text, **kw)
        return {'message_id': mid, 'channel': 'telegram', 'chat_id': self.channel_id}

    async def update_schedule(self, schedule_data: Dict, message_id: int, **kw) -> Dict:
        text = self._fmt_schedule(schedule_data)
        await self.edit_message(self.channel_id, message_id, text, **kw)
        return {'message_id': message_id, 'channel': 'telegram', 'chat_id': self.channel_id}

    async def send_reminder(self, user_id: str, reminder_data: Dict) -> bool:
        try:
            from src.utils.formatter import ScheduleFormatter
            await self.send_message(user_id, ScheduleFormatter.format_reminder(reminder_data))
            return True
        except Exception as e:
            logger.error(f"send_reminder error: {e}"); return False

    async def get_user_info(self, user_id: str) -> Dict:
        try:
            u = await self.bot.get_chat(user_id)
            return {'id': u.id, 'username': u.username,
                    'first_name': u.first_name, 'last_name': u.last_name}
        except Exception as e:
            logger.error(f"get_user_info error: {e}"); return {}

    def _fmt_schedule(self, schedule_data: Dict) -> str:
        from src.utils.formatter import ScheduleFormatter
        days = schedule_data.get('days', [])
        if not days:
            return "Расписание недоступно"
        week_start = days[0].get('date', date.today())
        return ScheduleFormatter.format_week_schedule(days, week_start)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _register_handlers(self):
        dp = self.dp

        # ── Commands ──────────────────────────────────────────────────────────

        @dp.message(Command('start'))
        async def cmd_start(msg: Message):
            name = msg.from_user.first_name or 'друг'
            is_adm = self._is_admin(msg.from_user.id)
            text = (
                f"Привет, {name}! Я бот для записи на тренировки.\n\n"
                "/schedule — расписание на текущую неделю\n"
                "/book — подать заявку на тренировку"
            )
            if is_adm:
                text += "\n/admin — панель администратора"
            await msg.answer(text)

        @dp.message(Command('schedule'))
        async def cmd_schedule(msg: Message):
            db = self._db()
            try:
                from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
                ws   = _this_monday()
                days = ScheduleGenerator.generate_from_db(db, ws)
                text = ScheduleFormatter.format_week_schedule(days, ws)
            except Exception as e:
                logger.error(e); text = "Не удалось получить расписание."
            finally:
                db.close()
            await msg.answer(text)

        @dp.message(Command('book'))
        async def cmd_book(msg: Message):
            db = self._db()
            try:
                from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
                ws   = _this_monday()
                days = ScheduleGenerator.generate_from_db(db, ws)
                # Собираем только bookable тренировки
                rows = []
                for day in days:
                    for e in day.get('entries', []):
                        if e['type'] != 'basic' and not e.get('is_cancelled'):
                            d = day['date']
                            label = f"{d.strftime('%d.%m')} {e['time'].split('-')[0]} — {e['title']}"
                            rows.append([_btn(label, f"book:{e['id']}")])
                if not rows:
                    await msg.answer("Нет доступных тренировок для записи.")
                    return
                rows.append([_btn('Отмена', 'book:cancel')])
                await msg.answer(
                    "Выберите тренировку для записи:",
                    reply_markup=_kb(*rows)
                )
            except Exception as e:
                logger.error(e); await msg.answer("Ошибка.")
            finally:
                db.close()

        @dp.callback_query(F.data.startswith('book:'))
        async def cb_book(call: CallbackQuery):
            await call.answer()
            if call.data == 'book:cancel':
                await call.message.delete()
                return
            entry_id = int(call.data.split(':')[1])
            db = self._db()
            try:
                from src.models.models import ScheduleEntry, Booking, User
                from src.models.enums import BookingStatus

                entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == entry_id).first()
                if not entry:
                    await call.message.answer("Тренировка не найдена.")
                    return

                # Найти или создать пользователя
                user = db.query(User).filter(User.telegram_id == call.from_user.id).first()
                if not user:
                    user = User(
                        telegram_id=call.from_user.id,
                        username=call.from_user.username,
                        first_name=call.from_user.first_name or '',
                        last_name=call.from_user.last_name,
                    )
                    db.add(user); db.commit(); db.refresh(user)

                # Проверить дубль
                existing = db.query(Booking).filter(
                    Booking.user_id == user.id,
                    Booking.schedule_entry_id == entry_id,
                    Booking.status != BookingStatus.CANCELLED,
                ).first()
                if existing:
                    await call.message.answer("Вы уже подали заявку на эту тренировку.")
                    return

                booking = Booking(
                    user_id=user.id,
                    training_id=entry.training_id,
                    schedule_entry_id=entry_id,
                    status=BookingStatus.PENDING,
                )
                db.add(booking); db.commit(); db.refresh(booking)

                await call.message.answer(
                    f"✅ Заявка принята! Ожидайте подтверждения от администратора.\n"
                    f"Тренировка: {entry.training.title}\n"
                    f"Дата: {entry.date.strftime('%d.%m.%Y')} в {entry.start_time}"
                )

                # Уведомить администраторов
                admin_ids = settings.TELEGRAM_ADMIN_IDS
                if isinstance(admin_ids, list):
                    notif = (
                        f"📋 Новая заявка!\n"
                        f"👤 {user.first_name} {user.last_name or ''} (@{user.username or '—'})\n"
                        f"🏋️ {entry.training.title}\n"
                        f"📅 {entry.date.strftime('%d.%m.%Y')} в {entry.start_time}\n\n"
                        f"Подтвердить: /admin"
                    )
                    for aid in admin_ids:
                        try:
                            await self.bot.send_message(aid, notif)
                        except Exception:
                            pass
            except Exception as e:
                logger.error(e); await call.message.answer("Ошибка при записи.")
            finally:
                db.close()

        @dp.message(Command('admin'))
        async def cmd_admin(msg: Message):
            if not self._is_admin(msg.from_user.id):
                await msg.answer("У вас нет прав администратора.")
                return
            await msg.answer("Панель администратора:", reply_markup=_admin_kb())

        # ── Admin: menu ───────────────────────────────────────────────────────

        @dp.callback_query(F.data == 'a:menu')
        async def cb_menu(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            await call.message.edit_text("Панель администратора:", reply_markup=_admin_kb())

        # ── Admin: schedule ───────────────────────────────────────────────────

        @dp.callback_query(F.data == 'a:schedule')
        async def cb_schedule(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            cw, nw = _this_monday(), _next_monday()
            kb = _kb(
                [_btn(f"📅 Текущая неделя ({_week_label(cw)})", f"a:gen:{cw.isoformat()}")],
                [_btn(f"📅 Следующая неделя ({_week_label(nw)})", f"a:gen:{nw.isoformat()}")],
                _back(),
            )
            await call.message.edit_text("Выберите неделю для генерации расписания:", reply_markup=kb)

        @dp.callback_query(F.data.startswith('a:gen:'))
        async def cb_generate(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer("Генерирую...")
            ws = date.fromisoformat(call.data.split(':', 2)[2])
            db = self._db()
            try:
                from src.business_logic.services.schedule_service import ScheduleService
                svc     = ScheduleService(db)
                entries = svc.generate_weekly_schedule(ws)
                text    = f"✅ Сгенерировано {len(entries)} занятий на неделю {_week_label(ws)}."
                kb = _kb(
                    [_btn(f"📢 Опубликовать эту неделю", f"a:pub:{ws.isoformat()}")],
                    _back('a:schedule'),
                )
                await call.message.edit_text(text, reply_markup=kb)
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}", reply_markup=_kb(_back('a:schedule')))
            finally:
                db.close()

        # ── Admin: publish ────────────────────────────────────────────────────

        @dp.callback_query(F.data == 'a:publish')
        async def cb_publish_menu(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            cw, nw = _this_monday(), _next_monday()
            kb = _kb(
                [_btn(f"Текущая неделя ({_week_label(cw)})", f"a:pub:{cw.isoformat()}")],
                [_btn(f"Следующая неделя ({_week_label(nw)})", f"a:pub:{nw.isoformat()}")],
                _back(),
            )
            await call.message.edit_text("Выберите неделю для публикации:", reply_markup=kb)

        @dp.callback_query(F.data.startswith('a:pub:'))
        async def cb_publish(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer("Формирую превью...")
            ws = date.fromisoformat(call.data.split(':', 2)[2])
            db = self._db()
            try:
                from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
                days    = ScheduleGenerator.generate_from_db(db, ws)
                preview = ScheduleFormatter.format_week_schedule(days, ws)
                # Показываем превью и кнопку подтверждения
                kb = _kb(
                    [_btn("✅ Опубликовать", f"a:pub_ok:{ws.isoformat()}")],
                    _back('a:publish'),
                )
                # Telegram ограничивает edit_text до 4096 символов
                text = f"<b>Превью расписания {_week_label(ws)}:</b>\n\n{preview}"
                if len(text) > 4000:
                    text = text[:3990] + "\n..."
                await call.message.edit_text(text, reply_markup=kb)
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}", reply_markup=_kb(_back('a:publish')))
            finally:
                db.close()

        @dp.callback_query(F.data.startswith('a:pub_ok:'))
        async def cb_publish_confirm(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer("Публикую...")
            ws = date.fromisoformat(call.data.split(':', 2)[2])
            db = self._db()
            try:
                from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
                from src.business_logic.services.schedule_service import ScheduleService
                from src.celery_app import publish_schedule_to_channels

                days    = ScheduleGenerator.generate_from_db(db, ws)
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
                await call.message.edit_text(
                    f"📢 Расписание на {_week_label(ws)} опубликовано!",
                    reply_markup=_kb(_back()),
                )
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка публикации: {e}", reply_markup=_kb(_back()))
            finally:
                db.close()

        # ── Admin: templates ──────────────────────────────────────────────────

        @dp.callback_query(F.data.startswith('a:templates'))
        async def cb_templates(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            page = int(call.data.split(':')[2]) if call.data.count(':') == 2 else 0
            db   = self._db()
            try:
                from src.models.models import Training
                all_t = db.query(Training).filter(Training.is_active == True)\
                          .order_by(Training.day_of_week, Training.start_time).all()
                per_page = 6
                chunk    = all_t[page * per_page: (page + 1) * per_page]
                rows     = []
                for t in chunk:
                    label = f"{RU_DAYS[t.day_of_week][:2]} {t.start_time} — {t.title}"
                    rows.append([_btn(label, f"a:tmpl:{t.id}")])
                # Пагинация
                nav = []
                if page > 0:
                    nav.append(_btn("‹", f"a:templates:{page-1}"))
                if (page + 1) * per_page < len(all_t):
                    nav.append(_btn("›", f"a:templates:{page+1}"))
                if nav:
                    rows.append(nav)
                rows.append([_btn("➕ Добавить шаблон", 'a:tmpl_add')])
                rows.append(_back())
                text = f"📋 Шаблоны тренировок ({len(all_t)}):"
                await call.message.edit_text(text, reply_markup=_kb(*rows))
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}", reply_markup=_kb(_back()))
            finally:
                db.close()

        @dp.callback_query(F.data.startswith('a:tmpl:'))
        async def cb_template_detail(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            tid = int(call.data.split(':')[2])
            db  = self._db()
            try:
                from src.models.models import Training
                t = db.query(Training).filter(Training.id == tid).first()
                if not t:
                    await call.answer("Не найдено", show_alert=True); return
                text = (
                    f"<b>{t.title}</b>\n"
                    f"Тип: {TRAINING_TYPES.get(t.training_type.value, t.training_type.value)}\n"
                    f"День: {RU_DAYS[t.day_of_week]}\n"
                    f"Время: {t.start_time}, {t.duration_minutes} мин.\n"
                    f"Макс. участников: {t.max_participants or 'без ограничений'}\n"
                    f"Описание: {t.description or '—'}"
                )
                kb = _kb(
                    [_btn("🗑 Удалить", f"a:tmpl_del:{tid}")],
                    _back('a:templates'),
                )
                await call.message.edit_text(text, reply_markup=kb)
            except Exception as e:
                logger.error(e)
            finally:
                db.close()

        @dp.callback_query(F.data.startswith('a:tmpl_del:'))
        async def cb_template_delete(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            tid = int(call.data.split(':')[2])
            kb  = _kb(
                [_btn("✅ Да, удалить", f"a:tmpl_del_ok:{tid}")],
                _back('a:templates'),
            )
            await call.message.edit_text("Удалить этот шаблон?", reply_markup=kb)

        @dp.callback_query(F.data.startswith('a:tmpl_del_ok:'))
        async def cb_template_delete_ok(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            tid = int(call.data.split(':')[2])
            db  = self._db()
            try:
                from src.models.models import Training
                t = db.query(Training).filter(Training.id == tid).first()
                if t:
                    t.is_active = False
                    db.commit()
                await call.message.edit_text("✅ Шаблон удалён.", reply_markup=_kb(_back('a:templates')))
            except Exception as e:
                logger.error(e)
            finally:
                db.close()

        # ── FSM: add training template ────────────────────────────────────────

        @dp.callback_query(F.data == 'a:tmpl_add')
        async def cb_tmpl_add_start(call: CallbackQuery, state: FSMContext):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            await state.set_state(AddTraining.title)
            await call.message.edit_text(
                "Введите <b>название</b> тренировки:\n(или /cancel для отмены)"
            )

        @dp.message(AddTraining.title)
        async def fsm_title(msg: Message, state: FSMContext):
            await state.update_data(title=msg.text.strip())
            await state.set_state(AddTraining.training_type)
            kb = _kb(
                [_btn('Персональная',   'fsm_type:personal')],
                [_btn('Коммерческая 💸','fsm_type:commercial')],
                [_btn('Базовая',        'fsm_type:basic')],
            )
            await msg.answer("Выберите <b>тип</b> тренировки:", reply_markup=kb)

        @dp.callback_query(F.data.startswith('fsm_type:'))
        async def fsm_type(call: CallbackQuery, state: FSMContext):
            await call.answer()
            await state.update_data(training_type=call.data.split(':')[1])
            await state.set_state(AddTraining.day_of_week)
            kb = _kb(
                [_btn('Пн', 'fsm_day:0'), _btn('Вт', 'fsm_day:1'), _btn('Ср', 'fsm_day:2')],
                [_btn('Чт', 'fsm_day:3'), _btn('Пт', 'fsm_day:4')],
                [_btn('Сб', 'fsm_day:5'), _btn('Вс', 'fsm_day:6')],
            )
            await call.message.edit_text("Выберите <b>день недели</b>:", reply_markup=kb)

        @dp.callback_query(F.data.startswith('fsm_day:'))
        async def fsm_day(call: CallbackQuery, state: FSMContext):
            await call.answer()
            await state.update_data(day_of_week=int(call.data.split(':')[1]))
            await state.set_state(AddTraining.start_time)
            await call.message.edit_text("Введите <b>время начала</b> (ЧЧ:ММ), например: 19:30")

        @dp.message(AddTraining.start_time)
        async def fsm_time(msg: Message, state: FSMContext):
            import re
            if not re.match(r'^\d{1,2}:\d{2}$', msg.text.strip()):
                await msg.answer("Формат: ЧЧ:ММ, например 09:00"); return
            await state.update_data(start_time=msg.text.strip())
            await state.set_state(AddTraining.duration)
            await msg.answer("Введите <b>продолжительность</b> в минутах (например: 60):")

        @dp.message(AddTraining.duration)
        async def fsm_duration(msg: Message, state: FSMContext):
            if not msg.text.strip().isdigit():
                await msg.answer("Введите число минут, например: 60"); return
            await state.update_data(duration_minutes=int(msg.text.strip()))
            await state.set_state(AddTraining.max_participants)
            await msg.answer(
                "Максимальное количество участников?\n"
                "(введите число или /skip для неограниченного)"
            )

        @dp.message(AddTraining.max_participants)
        async def fsm_max(msg: Message, state: FSMContext):
            text = msg.text.strip()
            max_p = None
            if text != '/skip':
                if not text.isdigit():
                    await msg.answer("Введите число или /skip"); return
                max_p = int(text)
            await state.update_data(max_participants=max_p)

            data = await state.get_data()
            summary = (
                f"<b>Проверьте данные:</b>\n"
                f"Название: {data['title']}\n"
                f"Тип: {TRAINING_TYPES.get(data['training_type'], data['training_type'])}\n"
                f"День: {RU_DAYS[data['day_of_week']]}\n"
                f"Время: {data['start_time']}, {data['duration_minutes']} мин.\n"
                f"Макс. участников: {max_p or 'без ограничений'}"
            )
            kb = _kb(
                [_btn('✅ Сохранить', 'fsm_confirm'), _btn('❌ Отмена', 'fsm_cancel')],
            )
            await msg.answer(summary, reply_markup=kb)

        @dp.callback_query(F.data == 'fsm_confirm')
        async def fsm_confirm(call: CallbackQuery, state: FSMContext):
            await call.answer()
            data = await state.get_data()
            await state.clear()
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
                await call.message.edit_text(
                    f"✅ Шаблон «{t.title}» добавлен!",
                    reply_markup=_kb(_back('a:templates')),
                )
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}", reply_markup=_kb(_back('a:templates')))
            finally:
                db.close()

        @dp.callback_query(F.data == 'fsm_cancel')
        async def fsm_cancel_cb(call: CallbackQuery, state: FSMContext):
            await call.answer()
            await state.clear()
            await call.message.edit_text("Отменено.", reply_markup=_kb(_back('a:templates')))

        @dp.message(Command('cancel'))
        async def cmd_cancel(msg: Message, state: FSMContext):
            await state.clear()
            await msg.answer("Отменено. /admin — вернуться в меню.")

        # ── Admin: bookings ───────────────────────────────────────────────────

        @dp.callback_query(F.data.startswith('a:bookings'))
        async def cb_bookings(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer()
            page = int(call.data.split(':')[2]) if call.data.count(':') == 2 else 0
            db   = self._db()
            try:
                from src.models.models import Booking, ScheduleEntry, User, Training
                from src.models.enums import BookingStatus
                all_b = (
                    db.query(Booking)
                    .filter(Booking.status == BookingStatus.PENDING)
                    .order_by(Booking.created_at)
                    .all()
                )
                if not all_b:
                    await call.message.edit_text(
                        "👥 Нет заявок, требующих подтверждения.",
                        reply_markup=_kb(_back()),
                    )
                    return

                per_page = 5
                chunk    = all_b[page * per_page: (page + 1) * per_page]
                rows     = []
                for b in chunk:
                    user = db.query(User).filter(User.id == b.user_id).first()
                    entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == b.schedule_entry_id).first()
                    uname = f"{user.first_name} {user.last_name or ''}".strip() if user else "?"
                    t_name = entry.training.title if entry else "?"
                    t_date = entry.date.strftime('%d.%m %H:%M') if entry else "?"
                    rows.append([
                        _btn(f"✅ {uname} / {t_name} {t_date}", f"a:book_ok:{b.id}"),
                    ])
                    rows.append([
                        _btn(f"❌ Отклонить эту заявку", f"a:book_no:{b.id}"),
                    ])

                nav = []
                if page > 0:
                    nav.append(_btn("‹", f"a:bookings:{page-1}"))
                if (page + 1) * per_page < len(all_b):
                    nav.append(_btn("›", f"a:bookings:{page+1}"))
                if nav:
                    rows.append(nav)
                rows.append(_back())

                await call.message.edit_text(
                    f"👥 Заявки на подтверждение ({len(all_b)}):",
                    reply_markup=_kb(*rows),
                )
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}", reply_markup=_kb(_back()))
            finally:
                db.close()

        @dp.callback_query(F.data.startswith('a:book_ok:'))
        async def cb_booking_confirm(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer("Подтверждаю...")
            bid = int(call.data.split(':')[2])
            db  = self._db()
            try:
                from src.models.models import Booking, User, ScheduleEntry
                from src.models.enums import BookingStatus
                b = db.query(Booking).filter(Booking.id == bid).first()
                if not b:
                    await call.answer("Заявка не найдена", show_alert=True); return
                b.status = BookingStatus.CONFIRMED
                db.commit()

                # Уведомить пользователя
                user  = db.query(User).filter(User.id == b.user_id).first()
                entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == b.schedule_entry_id).first()
                if user and user.telegram_id and entry:
                    try:
                        await self.bot.send_message(
                            user.telegram_id,
                            f"✅ Ваша запись подтверждена!\n"
                            f"🏋️ {entry.training.title}\n"
                            f"📅 {entry.date.strftime('%d.%m.%Y')} в {entry.start_time}"
                        )
                    except Exception:
                        pass

                await call.message.edit_text(
                    f"✅ Заявка #{bid} подтверждена.",
                    reply_markup=_kb([_btn("← К заявкам", 'a:bookings')]),
                )
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}")
            finally:
                db.close()

        @dp.callback_query(F.data.startswith('a:book_no:'))
        async def cb_booking_reject(call: CallbackQuery):
            if not self._is_admin(call.from_user.id):
                await call.answer("Нет доступа", show_alert=True); return
            await call.answer("Отклоняю...")
            bid = int(call.data.split(':')[2])
            db  = self._db()
            try:
                from src.models.models import Booking, User, ScheduleEntry
                from src.models.enums import BookingStatus
                b = db.query(Booking).filter(Booking.id == bid).first()
                if not b:
                    await call.answer("Заявка не найдена", show_alert=True); return
                b.status = BookingStatus.CANCELLED
                b.notes  = "Отклонено администратором"
                db.commit()

                user  = db.query(User).filter(User.id == b.user_id).first()
                entry = db.query(ScheduleEntry).filter(ScheduleEntry.id == b.schedule_entry_id).first()
                if user and user.telegram_id and entry:
                    try:
                        await self.bot.send_message(
                            user.telegram_id,
                            f"❌ К сожалению, ваша запись на тренировку отклонена.\n"
                            f"🏋️ {entry.training.title}\n"
                            f"По вопросам обратитесь к администратору."
                        )
                    except Exception:
                        pass

                await call.message.edit_text(
                    f"❌ Заявка #{bid} отклонена.",
                    reply_markup=_kb([_btn("← К заявкам", 'a:bookings')]),
                )
            except Exception as e:
                logger.error(e)
                await call.message.edit_text(f"Ошибка: {e}")
            finally:
                db.close()

    # ── Run ───────────────────────────────────────────────────────────────────

    async def run(self):
        logger.info("Starting Telegram bot (polling)...")
        await self.dp.start_polling(self.bot)


# Register with factory
from src.messengers.interfaces.messenger import MessengerFactory
MessengerFactory.register("telegram", TelegramBot)
