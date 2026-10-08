# VK bot: next steps

Порядок работ после добавления системы приглашений ВК (ветка `feature/vk-invite-system`).

1. [x] Переписать `src/messengers/vk/bot.py` с vk_api на vkbottle — см. [migrate-vk-bot-to-vkbottle.md](migrate-vk-bot-to-vkbottle.md)
2. [x] Раннер: `scripts/run_vk_bot.py` + сервис `vk-bot` в docker-compose
3. [x] Повторить функционал Telegram-бота в VK (команды, админ-панель, FSM, запись на тренировку)
   - [x] тесты VK-бота: `tests/` (197 шт., моки, без БД/сети), см. README → «Тесты»
4. [ ] Развернуть на тестовой локальной ВМ
5. [ ] Подключить группу/сообщество к боту
6. [ ] Протестировать создание поста с расписанием в чате группы
7. [ ] Протестировать редактирование поста, удаление поста

## Фаза 0 — починки (после обкатки VK, до рефакторинга)

**Перед началом Фазы 0:** написать такие же тесты для Telegram-бота (`tests/telegram/`) —
они зафиксируют текущее поведение эталона, и рефакторинг можно будет делать под
защитой (поведение до/после сравнивается тестами, а не на глаз).
- [ ] тесты Telegram-бота по образцу `tests/vk/` (aiogram: `CallbackQuery`/`Message` моками, `FSMContext` на `MemoryStorage`)

Хендлеры обоих ботов работают с БД напрямую вместо вызова сервисов, из-за чего
теряются проверки и аудит. Разбито на независимые задачи:

- [ ] `create_training` → `AdminService.create_training` — возвращает `_check_time_conflict`
      (сейчас шаблоны можно создать в наложение) и запись в `admin_actions`
- [ ] `confirm_booking` / `reject_booking` → `AdminService.*` — возвращает аудит
- [ ] `delete_training` → `AdminService.delete_training` — возвращает аудит
- [ ] `create_booking` → `ScheduleService.create_booking`
- [ ] `get_pending_bookings` → `AdminService.get_pending_bookings`

## Фаза 1+ — абстракция слоя взаимодействия

- [ ] Вынести диалоги (экраны, кнопки, FSM) в платформенно-независимый слой;
      боты становятся адаптерами рендеринга
- [ ] Обобщить веер публикации: `published_schedule_targets(schedule_id, channel, external_id)`
      вместо колонок `telegram_message_id` / `vk_post_id`
- [ ] Обобщить идентичность: `user_identities(user_id, channel, external_id)`
      вместо `User.telegram_id` / `User.vk_id`
- [ ] Реестр включённых каналов в одном месте вместо россыпи `if settings.*`
- [ ] Убрать дубли `vk_bot_main.py` / `src/messengers/vk/long_poll_bot.py`
- [ ] Убрать `VK_CONFIRMATION_CODE` / `VK_SECRET_KEY` (Callback API не используется)
- [ ] Дедуплицировать `RU_DAYS` / `TRAINING_TYPES` (сейчас в обоих ботах)

## Ограничения текущих тестов

- Моки не проверяют реальное поведение VK API: допущения о `vkbottle`
  (`event.user_id`, `edit_message`, формат payload) подтвердит только запуск
  против живой группы (пункты 4–7).
- `FakeSession` не вычисляет фильтры SQL — запросы проверяются только на ВМ/в
  интеграционных тестах с реальной БД (пока их нет).

## Известные дефекты эталона (Telegram), не исправлены намеренно

- `Bot(token=...)` создаётся без `parse_mode`, поэтому теги `<b>` в текстах
  TG-бота показываются пользователю буквально. В VK-боте разметки нет вообще —
  там текст изначально чистый.
