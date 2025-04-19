# Challenge Bot

Telegram-бот для группового челленджа и учёта целей.

## Функциональность

- Регистрация пользователей с указанием цели и смайлика
- Отметка выполнения целей за конкретные даты
- Просмотр статистики выполнения целей
- Поддержка групповых чатов

## Команды

- `/start` - Начать регистрацию
- `/complete ДД.ММ.ГГГГ` - Отметить выполнение цели
- `/result ДД.ММ.ГГГГ` - Показать результаты за день
- `/result_all` - Общая статистика
- `/result_month` - Статистика за последние 30 дней
- `/result_step ДД.ММ.ГГГГ` - Статистика с указанной даты
- `/help` - Справка по командам

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/your-username/challenge-bot.git
cd challenge-bot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env` и добавьте в него:
```
TOKEN=your_telegram_bot_token
DB_URL=your_database_url
```

4. Примените миграции:
```bash
alembic upgrade head
```

5. Запустите бота:
```bash
python bot/main.py
```

## Развертывание на Render.com

1. Создайте новый Web Service на Render.com
2. Подключите ваш GitHub репозиторий
3. Укажите следующие настройки:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot/main.py`
4. Добавьте переменные окружения:
   - `TOKEN`
   - `DB_URL`
5. Нажмите "Create Web Service"

## Технологии

- Python 3.8+
- aiogram 3.3.0
- SQLAlchemy 2.0.25
- PostgreSQL
- Alembic 