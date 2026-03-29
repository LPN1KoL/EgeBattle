# EGE Battle

Многопользовательская онлайн-игра для подготовки к ЕГЭ. Игроки соревнуются в решении задач в реальном времени, выбирая сложность и зарабатывая очки.

## Возможности

- Мультиплеер в реальном времени через WebSocket
- Выбор сложности (1-5) каждым игроком в каждом раунде
- 5 предметов: математика, русский язык, физика, информатика, обществознание
- Telegram-бот для создания комнат и приглашения друзей
- Таблица лидеров и профиль с детальной статистикой по предметам
- Автоудаление пустых комнат через 2 минуты без активных подключений

## Стек технологий

- **Backend:** Django 5 + Django Channels (ASGI/Daphne)
- **WebSocket:** Channels с InMemoryChannelLayer (dev) / Redis (prod)
- **Telegram-бот:** aiogram 3
- **Frontend:** Django Templates + Vanilla JS
- **БД:** PostgreSQL
- **Аутентификация:** HMAC-подписанные ссылки из Telegram, сессии Django

## Установка

```bash
# Клонировать репозиторий
git clone <repo-url>
cd EGE-game

# Создать виртуальное окружение
python -m venv venv
source venv/Scripts/activate   # Windows Git Bash
# или: venv\Scripts\activate   # Windows CMD

# Установить зависимости
pip install django channels daphne aiogram python-dotenv psycopg2-binary

# Настроить переменные окружения
cp .env.example .env
# Отредактировать .env (см. раздел "Переменные окружения")

# Создать базу данных PostgreSQL
createdb ege_game

# Применить миграции
python manage.py migrate

# Загрузить задания
python manage.py load_tasks --dir tasks/ --clear
```

## Переменные окружения

Файл `.env` в корне проекта:

| Переменная     | Описание                                      | По умолчанию       |
|----------------|-----------------------------------------------|---------------------|
| `BOT_TOKEN`    | Токен Telegram-бота                           | —                   |
| `BOT_USERNAME` | Username бота (без @)                         | —                   |
| `BASE_URL`     | Публичный URL сервера (ngrok для разработки)  | `http://localhost:8000` |
| `HMAC_SECRET`  | Секрет для подписи ссылок                     | `BOT_TOKEN`         |
| `DB_NAME`      | Имя базы данных PostgreSQL                    | `ege_game`          |
| `DB_USER`      | Пользователь PostgreSQL                       | `postgres`          |
| `DB_PASSWORD`  | Пароль PostgreSQL                             | —                   |
| `DB_HOST`      | Хост PostgreSQL                               | `localhost`         |
| `DB_PORT`      | Порт PostgreSQL                               | `5432`              |
| `DJANGO_DEBUG` | Режим отладки                                 | `False`             |

## Запуск

```bash
# Сервер (ASGI — обязательно для WebSocket)
python manage.py runserver

# Telegram-бот (отдельный процесс)
python manage.py run_bot
```

Для доступа извне (Telegram-ссылки) используйте ngrok:

```bash
ngrok http 8000
# Обновить BASE_URL в .env на полученный URL
```

## Как играть

1. **Создать комнату** — через команду `/play` в Telegram-боте или кнопку на сайте (для авторизованных)
2. **Пригласить друзей** — поделиться ссылкой-приглашением
3. **Выбрать настройки** — предметы и количество раундов в лобби
4. **Решать задачи** — в каждом раунде выбрать сложность (1-5), получить задачу и ответить до истечения таймера
5. **Набирать очки** — правильный ответ: `+сложность * 10`, неправильный/пропуск: `-сложность * 10`

## Команды бота

| Команда        | Описание                          |
|----------------|-----------------------------------|
| `/start`       | Приветствие и список команд       |
| `/play`        | Создать комнату                   |
| `/games`       | Список открытых комнат            |
| `/leaderboard` | Таблица лидеров                   |

## Структура проекта

```
EGE-game/
├── ege_game/           # Конфигурация Django (settings, ASGI, URLs)
├── game/               # Основное приложение
│   ├── models.py       # Модели: TelegramUser, Task, Room, GameSession и др.
│   ├── consumers.py    # WebSocket: RoomConsumer (лобби), GameConsumer (игра)
│   ├── bot.py          # Telegram-бот (aiogram 3)
│   ├── views.py        # HTTP-представления
│   └── management/     # Management-команды (load_tasks, run_bot)
├── templates/          # Django-шаблоны
├── static/             # Статика (CSS, JS)
└── tasks/              # JSON-файлы с заданиями ЕГЭ
```

## Dev-режим

Для локального тестирования без Telegram доступен обход аутентификации:

```
/dev/room/<uuid>/?tg_id=123&username=test
```
