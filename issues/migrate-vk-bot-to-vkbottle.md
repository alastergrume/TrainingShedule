# Migrate src/messengers/vk/bot.py from vk_api to vkbottle

## Context

The project currently uses two VK libraries:
- `vk_api` — in `src/messengers/vk/bot.py` (VKBot class, wall posts, messages, reminders)
- `vkbottle` — in `src/messengers/vk/long_poll_bot.py`, `vk_bot_main.py`, invite system (`src/routers/vk_invite.py`, `src/celery_app.py`)

This creates unnecessary dependency duplication and inconsistency.

## Task

Rewrite `src/messengers/vk/bot.py` to use `vkbottle` instead of `vk_api`, preserving the `MessengerInterface` contract.

## What needs to migrate

- `VKBot.__init__` — replace `vk_api.VkApi` + `VkBotLongPoll` with `vkbottle.Bot` / `vkbottle.API`
- `send_message` — `messages.send` via vkbottle API
- `edit_message` / `delete_message` — adapt to vkbottle
- `send_schedule` — `wall.post` via vkbottle API
- `update_schedule` — `wall.edit` via vkbottle API
- `check_post_exists` — `wall.getById` via vkbottle API
- `send_reminder` — reuse `send_message`
- `get_user_info` — `users.get` via vkbottle API
- `process_event`, `_handle_*` — replace `VkBotLongPoll` event handlers with vkbottle decorators
- `run()` — replace longpoll loop with `bot.run_forever()`

## After migration

- Remove `vk_api` from `requirements.txt`
- Remove `VK_CONFIRMATION_CODE` and `VK_SECRET_KEY` from config (only needed for Callback API, not used with longpoll)
- Verify Celery tasks that use `MessengerFactory.create('vk')` still work
- Test: wall posting, message sending, reminders
