# Training Schedule Bot

Бот для формирования расписания тренировок на неделю с поддержкой Telegram и VK.

## Описание

Приложение представляет собой бота социальных сетей, который работает с несколькими социальными сетями (Telegram, VK) и направлен на формирование расписания тренировок на неделю в спортивном зале по заданному шаблону.

## Основные функции

1. **Формирование расписания тренировок на неделю**
   - Администратор формирует перечень тренировок на неделю
   - Тренировки повторяются еженедельно с возможностью изменений
   - Поддержка трех типов тренировок: персональные, коммерческие, базовые

2. **Публикация расписания**
   - Автоматическая публикация в Telegram-канал и VK группу
   - Закрепление сообщения в чате
   - Обновление сообщения при изменениях

3. **Запись пользователей на тренировки**
   - Пользователи могут записываться через бота
   - Администратор подтверждает/редактирует записи
   - Автоматическое обновление опубликованного расписания

4. **Напоминания о тренировках**
   - Автоматические напоминания за 60 минут до тренировки
   - Подтверждение участия
   - Настройка времени напоминаний

5. **Управление оплатами**
   - Отметка об оплате в расписании
   - Интеграция с MiniAPP для отметки оплаты

## Технологический стек

- **Backend**: FastAPI (Python)
- **База данных**: PostgreSQL
- **Очереди задач**: Celery + Redis
- **Боты**: Aiogram (Telegram), VK API
- **Контейнеризация**: Docker, Docker Compose
- **Планировщик**: Celery Beat

## Структура проекта

```
training-schedule/
├── src/
│   ├── models/           # Модели базы данных
│   ├── business_logic/   # Бизнес-логика формирования расписания
│   ├── messengers/       # Модули работы с мессенджерами
│   │   ├── telegram/     # Telegram бот (Aiogram)
│   │   ├── vk/           # VK бот
│   │   └── interfaces/   # Интерфейсы для мессенджеров
│   ├── utils/           # Вспомогательные утилиты
│   ├── config/          # Конфигурация приложения
│   └── main.py          # Основное приложение FastAPI
├── migrations/          # Миграции базы данных (Alembic)
├── docker/             # Docker конфигурации
├── requirements.txt    # Зависимости Python
├── docker-compose.yml  # Docker Compose
├── Dockerfile         # Docker образ
└── README.md          # Документация
```

## Быстрый старт

### Предварительные требования

- Docker и Docker Compose
- Python 3.11+ (для локальной разработки)
- Токены для Telegram бота и VK группы

### Запуск с Docker

1. Клонируйте репозиторий:
   ```bash
   git clone <repository-url>
   cd training-schedule
   ```

2. Создайте файл `.env` на основе `.env.example`:
   ```bash
   cp .env.example .env
   ```
   Заполните необходимые переменные окружения.

3. Запустите приложение:
   ```bash
   docker-compose up -d
   ```

4. Приложение будет доступно по адресам:
   - API: http://localhost:8000
   - Документация API: http://localhost:8000/docs
   - PostgreSQL: localhost:5432
   - Redis: localhost:6379

### Локальная разработка

1. Установите зависимости:
   ```bash
   pip install -r requirements.txt
   ```

2. Настройте базу данных:
   ```bash
   # Создайте базу данных PostgreSQL
   createdb training_schedule

   # Примените миграции
   alembic upgrade head
   ```

3. Запустите приложение:
   ```bash
   # Запуск FastAPI
   uvicorn src.main:app --reload

   # Запуск Celery worker (в отдельном терминале)
   celery -A src.celery_app worker --loglevel=info

   # Запуск Celery beat (в отдельном терминале)
   celery -A src.celery_app beat --loglevel=info
   ```

## Конфигурация

### Переменные окружения

Создайте файл `.env` со следующими переменными:

```env
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/training_schedule

# Redis
REDIS_URL=redis://localhost:6379/0

# Telegram
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHANNEL_ID=@your_channel
TELEGRAM_ADMIN_IDS=123456789,987654321

# VK
VK_GROUP_TOKEN=your_vk_group_token
VK_GROUP_ID=123456789
VK_CONFIRMATION_CODE=your_confirmation_code
VK_SECRET_KEY=your_secret_key

# Application
DEBUG=True
SECRET_KEY=your_secret_key_here
HOST=0.0.0.0
PORT=8000

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Reminder settings
REMINDER_MINUTES_BEFORE=60
ADMIN_NOTIFICATION_ENABLED=True
```

### Настройка Telegram бота

1. Создайте бота через [@BotFather](https://t.me/BotFather)
2. Получите токен бота
3. Добавьте бота в канал и сделайте администратором
4. Установите переменные окружения

### Настройка VK бота

1. Создайте группу ВКонтакте
2. Включите сообщества в настройках
3. Создайте ключ доступа с правами: messages, wall, groups
4. Настройте Callback API в разделе "Работа с API"
5. Установите переменные окружения

## API Endpoints

### Основные endpoints

- `GET /` - Информация о API
- `GET /health` - Проверка здоровья приложения
- `GET /api/schedule/week` - Получить расписание на неделю
- `POST /api/bookings` - Создать запись на тренировку
- `GET /api/admin/stats` - Статистика для администраторов

Полная документация доступна по адресу `/docs` после запуска приложения.

## Работа с ботом

### Команды Telegram бота

- `/start` - Начало работы с ботом
- `/schedule` - Показать текущее расписание
- `/book` - Записаться на тренировку
- `/admin` - Панель администратора (только для админов)

### Команды VK бота

- `начать` или `/start` - Начало работы
- `расписание` или `/schedule` - Показать расписание
- `записаться` или `/book` - Записаться на тренировку

## Разработка

### Добавление нового мессенджера

1. Создайте класс в `src/messengers/`, реализующий интерфейс `MessengerInterface`
2. Зарегистрируйте его в `MessengerFactory`
3. Добавьте конфигурационные переменные в `src/config/__init__.py`

### Расширение бизнес-логики

Бизнес-логика изолирована в `src/business_logic/`. Для добавления новой функциональности:

1. Добавьте методы в `ScheduleService`
2. Создайте соответствующие схемы в `src/business_logic/schemas/`
3. Добавьте API endpoints в `src/main.py`

### Миграции базы данных

```bash
# Создание новой миграции
alembic revision --autogenerate -m "Описание изменений"

# Применение миграций
alembic upgrade head

# Откат миграции
alembic downgrade -1
```

## Лицензия

MIT