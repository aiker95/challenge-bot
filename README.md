# Challenge Bot

Telegram бот для отслеживания целей и достижений в групповых челленджах.

## Функциональность

- Регистрация пользователей
- Отслеживание выполнения целей
- Просмотр статистики
- Групповые отчеты

## Команды

- `/start` - Начать регистрацию
- `/complete ДД.ММ.ГГГГ` - Отметить выполнение цели на указанную дату
- `/result ДД.ММ.ГГГГ` - Проверить выполнение цели на указанную дату
- `/result` - Показать все выполненные цели
- `/result_month` - Показать выполненные цели за текущий месяц
- `/result_step N` - Показать выполненные цели с шагом N
- `/help` - Показать справку по командам

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/your-username/challenge-bot.git
cd challenge-bot
```

2. Создайте виртуальное окружение и активируйте его:
```bash
python -m venv venv
source venv/bin/activate  # для Linux/Mac
venv\Scripts\activate     # для Windows
```

3. Установите зависимости:
```bash
pip install -r requirements.txt
```

4. Создайте файл `.env` и заполните его:
```
TOKEN=your_bot_token
DB_URL=postgresql+asyncpg://user:password@localhost:5432/dbname
WEBHOOK_URL=https://your-domain.com/webhook
PORT=8000
```

5. Создайте базу данных и примените миграции:
```bash
python run_migrations.py
```

## Запуск

1. Запустите бота:
```bash
python bot/main.py
```

## Развертывание на Render.com

1. Создайте новый Web Service на Render.com
2. Подключите ваш GitHub репозиторий
3. Настройте следующие переменные окружения:
   - `TOKEN` - токен вашего бота
   - `DB_URL` - URL базы данных PostgreSQL
   - `WEBHOOK_URL` - URL вашего сервиса на Render.com
   - `PORT` - порт (обычно 8000)

4. Настройте следующие параметры:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot/main.py`

## Лицензия

MIT 