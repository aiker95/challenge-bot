import asyncio
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, BotCommand, BotCommandScopeDefault
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Base, User, Completion, create_async_engine_from_url, create_async_session

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=os.getenv("TOKEN"))
dp = Dispatcher()

# Настройка базы данных
engine = create_async_engine_from_url(os.getenv("DB_URL"))
async_session = create_async_session(engine)

# Состояния регистрации
registration_states = {}
registration_locks = {}

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=1):
        self.limit = limit
        self.last_time = {}
        super().__init__()

    async def __call__(self, handler, event, data):
        if not isinstance(event, types.Message):
            return await handler(event, data)
            
        user_id = event.from_user.id
        current_time = datetime.now().timestamp()
        
        if user_id in self.last_time:
            if current_time - self.last_time[user_id] < self.limit:
                logger.warning(f"User {user_id} is being throttled")
                return
        self.last_time[user_id] = current_time
        return await handler(event, data)

class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, types.Message):
            logger.info(f"Handling message from user {event.from_user.id}: {event.text}")
        return await handler(event, data)

# Регистрация middleware
dp.update.middleware(ThrottlingMiddleware())
dp.update.middleware(LoggingMiddleware())

@dp.errors()
async def error_handler(update: types.Update, exception: Exception):
    logger.error(f"Update {update} caused error {exception}")
    if isinstance(exception, TelegramAPIError):
        logger.error(f"Telegram API error: {exception}")
    return True

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Received /start command from user {user_id}")
        
        # Создаем блокировку для пользователя, если её нет
        if user_id not in registration_locks:
            registration_locks[user_id] = asyncio.Lock()
            logger.info(f"Created new lock for user {user_id}")
        
        logger.info(f"Acquiring lock for user {user_id}")
        async with registration_locks[user_id]:
            logger.info(f"Lock acquired for user {user_id}")
            async with async_session() as session:
                result = await session.execute(
                    User.__table__.select().where(User.telegram_id == user_id)
                )
                user = result.first()
                
                if not user:
                    registration_states[user_id] = {
                        "step": 1,
                        "data": {},
                        "lock": asyncio.Lock()
                    }
                    logger.info(f"Starting registration for user {user_id}")
                    await message.answer("Давайте зарегистрируем вас! Как тебя зовут?")
                else:
                    logger.info(f"User {user_id} already registered")
                    await message.answer("Вы уже зарегистрированы!")
            logger.info(f"Releasing lock for user {user_id}")
    except Exception as e:
        logger.error(f"Error in cmd_start: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Received /stop command from user {user_id}")
        
        async with async_session() as session:
            # Находим пользователя
            user = await session.execute(
                select(User)
                .where(User.telegram_id == user_id)
            )
            user = user.scalar_one_or_none()
            
            if not user:
                await message.answer("Вы не зарегистрированы.")
                return
            
            # Удаляем все выполнения пользователя
            await session.execute(
                Completion.__table__.delete()
                .where(Completion.user_id == user.id)
            )
            
            # Удаляем пользователя
            await session.execute(
                User.__table__.delete()
                .where(User.id == user.id)
            )
            
            await session.commit()
            await message.answer("Ваши данные успешно удалены. Спасибо за участие!")
    except Exception as e:
        logger.error(f"Error in cmd_stop: {e}", exc_info=True)
        await message.answer("Произошла ошибка при удалении данных.")

@dp.message(Command("profile"))
async def cmd_profile(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Received /profile command from user {user_id}")
        
        async with async_session() as session:
            # Получаем пользователя
            user = await session.execute(
                select(User)
                .where(User.telegram_id == user_id)
            )
            user = user.scalar_one_or_none()
            
            if not user:
                await message.answer("Вы не зарегистрированы. Используйте команду /start для регистрации.")
                return
            
            # Получаем статистику выполнения
            completions = await session.execute(
                select(Completion)
                .where(Completion.user_id == user.id)
                .order_by(Completion.date)
            )
            completions = completions.scalars().all()
            
            # Получаем первую и последнюю дату выполнения
            dates = await session.execute(
                select(Completion.date)
                .order_by(Completion.date)
            )
            dates = dates.scalars().all()
            
            total_days = 0
            if dates:
                first_date = dates[0]
                last_date = dates[-1]
                total_days = (last_date - first_date).days + 1
            
            profile_message = (
                f"👤 Ваш профиль:\n\n"
                f"Имя: {user.name}\n"
                f"Цель: {user.goal}\n"
                f"Эмодзи: {user.emoji}\n"
                f"Выполнено дней: {len(completions)}/{total_days if total_days > 0 else '?'}\n"
                f"Дата регистрации: {user.created_at.strftime('%d.%m.%Y')}"
            )
            
            await message.answer(profile_message)
    except Exception as e:
        logger.error(f"Error in cmd_profile: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении профиля.")

@dp.message(Command("update"))
async def cmd_update(message: types.Message):
    try:
        user_id = message.from_user.id
        logger.info(f"Received /update command from user {user_id}")
        
        async with async_session() as session:
            # Получаем пользователя
            user = await session.execute(
                select(User)
                .where(User.telegram_id == user_id)
            )
            user = user.scalar_one_or_none()
            
            if not user:
                await message.answer("Вы не зарегистрированы. Используйте команду /start для регистрации.")
                return
            
            # Проверяем, есть ли текст после команды
            if not message.text or len(message.text.split()) < 2:
                await message.answer(
                    "Используйте команду в формате:\n"
                    "/update [имя/цель/эмодзи] [новое значение]\n\n"
                    "Примеры:\n"
                    "/update имя Иван\n"
                    "/update цель Бегать каждый день\n"
                    "/update эмодзи 🏃"
                )
                return
            
            # Разбираем команду
            parts = message.text.split(maxsplit=2)
            field = parts[1].lower()
            new_value = parts[2] if len(parts) > 2 else None
            
            if field not in ["имя", "цель", "эмодзи"]:
                await message.answer("Неверное поле для обновления. Используйте: имя, цель или эмодзи.")
                return
            
            if not new_value:
                await message.answer("Укажите новое значение.")
                return
            
            # Обновляем данные
            if field == "имя":
                user.name = new_value
            elif field == "цель":
                user.goal = new_value
            elif field == "эмодзи":
                user.emoji = new_value
            
            await session.commit()
            
            # Показываем обновленный профиль
            await cmd_profile(message)
    except Exception as e:
        logger.error(f"Error in cmd_update: {e}", exc_info=True)
        await message.answer("Произошла ошибка при обновлении профиля.")

@dp.message(Command("result"))
async def cmd_result(message: types.Message):
    try:
        logger.info(f"Received /result command from user {message.from_user.id}")
        
        async with async_session() as session:
            # Получаем всех пользователей
            users = await session.execute(select(User))
            users = users.scalars().all()
            
            if not users:
                await message.answer("Нет зарегистрированных пользователей.")
                return
            
            # Получаем первую и последнюю дату выполнения
            dates = await session.execute(
                select(Completion.date)
                .order_by(Completion.date)
            )
            dates = dates.scalars().all()
            
            if not dates:
                await message.answer("Пока нет выполненных целей.")
                return
            
            first_date = dates[0]
            last_date = dates[-1]
            total_days = (last_date - first_date).days + 1
            
            # Формируем сообщение для каждого пользователя
            result_message = "Результаты всех пользователей:\n\n"
            
            for user in users:
                # Получаем все выполнения для пользователя
                completions = await session.execute(
                    select(Completion)
                    .where(Completion.user_id == user.id)
                    .order_by(Completion.date)
                )
                completions = completions.scalars().all()
                
                completed_days = len(completions)
                result_message += f"{user.name} {user.emoji}: {completed_days}/{total_days}\n\n"
            
            await message.answer(result_message)
    except Exception as e:
        logger.error(f"Error in cmd_result: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении результатов.")

@dp.message(Command("result_day"))
async def cmd_result_day(message: types.Message):
    try:
        logger.info(f"Received /result_day command from user {message.from_user.id}")
        
        async with async_session() as session:
            # Получаем всех пользователей
            users = await session.execute(select(User))
            users = users.scalars().all()
            
            if not users:
                await message.answer("Нет зарегистрированных пользователей.")
                return
            
            # Получаем вчерашнюю дату
            yesterday = datetime.now().date() - timedelta(days=1)
            
            # Формируем сообщение
            result_message = f"Результаты за {yesterday.strftime('%d.%m.%Y')}:\n\n"
            
            for user in users:
                # Проверяем выполнение за вчера
                completion = await session.execute(
                    select(Completion)
                    .where(
                        Completion.user_id == user.id,
                        Completion.date == yesterday
                    )
                )
                completion = completion.scalar_one_or_none()
                
                if completion:
                    result_message += f"{user.name} {user.emoji}: ✅\n"
                else:
                    result_message += f"{user.name} {user.emoji}: ❌\n"
            
            await message.answer(result_message)
    except Exception as e:
        logger.error(f"Error in cmd_result_day: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении результатов за вчерашний день.")

@dp.message(Command("result_month"))
async def cmd_result_month(message: types.Message):
    try:
        logger.info(f"Received /result_month command from user {message.from_user.id}")
        
        async with async_session() as session:
            # Получаем всех пользователей
            users = await session.execute(select(User))
            users = users.scalars().all()
            
            if not users:
                await message.answer("Нет зарегистрированных пользователей.")
                return
            
            # Получаем текущий месяц
            today = datetime.now().date()
            first_day = today.replace(day=1)
            if today.month == 12:
                last_day = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                last_day = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            
            # Формируем сообщение
            result_message = f"Результаты за {today.strftime('%B %Y')}:\n\n"
            
            for user in users:
                # Получаем выполнения за текущий месяц
                completions = await session.execute(
                    select(Completion)
                    .where(
                        Completion.user_id == user.id,
                        Completion.date >= first_day,
                        Completion.date <= last_day
                    )
                    .order_by(Completion.date)
                )
                completions = completions.scalars().all()
                
                completed_days = len(completions)
                total_days = (last_day - first_day).days + 1
                result_message += f"{user.name} {user.emoji}: {completed_days}/{total_days}\n\n"
            
            await message.answer(result_message)
    except Exception as e:
        logger.error(f"Error in cmd_result_month: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении месячных результатов.")

@dp.message(Command("result_step"))
async def cmd_result_step(message: types.Message):
    try:
        logger.info(f"Received /result_step command from user {message.from_user.id}")
        
        async with async_session() as session:
            # Получаем всех пользователей
            users = await session.execute(select(User))
            users = users.scalars().all()
            
            if not users:
                await message.answer("Нет зарегистрированных пользователей.")
                return
            
            # Получаем все даты выполнения
            dates = await session.execute(
                select(Completion.date)
                .distinct()
                .order_by(Completion.date)
            )
            dates = dates.scalars().all()
            
            if not dates:
                await message.answer("Пока нет выполненных целей.")
                return
            
            # Формируем сообщение
            result_message = "Результаты по шагам:\n\n"
            
            for date in dates:
                result_message += f"{date.strftime('%d.%m.%Y')}:\n"
                for user in users:
                    # Проверяем выполнение для каждого пользователя
                    completion = await session.execute(
                        select(Completion)
                        .where(
                            Completion.user_id == user.id,
                            Completion.date == date
                        )
                    )
                    completion = completion.scalar_one_or_none()
                    
                    if completion:
                        result_message += f"{user.name} {user.emoji}\n"
                result_message += "\n"
            
            await message.answer(result_message)
    except Exception as e:
        logger.error(f"Error in cmd_result_step: {e}", exc_info=True)
        await message.answer("Произошла ошибка при получении результатов по шагам.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = """
Доступные команды:
/start - Начать регистрацию
/complete ДД.ММ.ГГГГ - Отметить выполнение цели на указанную дату
/result - Показать все выполненные цели
/result_day - Показать результаты за вчерашний день
/result_month - Показать результаты за текущий месяц
/result_step - Показать результаты по шагам
/profile - Показать свой профиль
/update [имя/цель/эмодзи] [значение] - Обновить данные профиля
/stop - Удалить свои данные
/help - Показать справку
"""
    await message.answer(help_text)

async def on_startup(bot: Bot) -> None:
    logger.info("Starting bot...")
    # Удаляем вебхук, если он существует
    await bot.delete_webhook()
    logger.info("Webhook deleted")
    
    # Регистрируем команды бота
    commands = [
        BotCommand(command="start", description="Начать регистрацию"),
        BotCommand(command="complete", description="Отметить выполнение цели"),
        BotCommand(command="result", description="Показать все результаты"),
        BotCommand(command="result_day", description="Показать результаты за вчера"),
        BotCommand(command="result_month", description="Показать результаты за месяц"),
        BotCommand(command="result_step", description="Показать результаты по шагам"),
        BotCommand(command="profile", description="Показать свой профиль"),
        BotCommand(command="update", description="Обновить данные профиля"),
        BotCommand(command="stop", description="Удалить свои данные"),
        BotCommand(command="help", description="Показать справку")
    ]
    
    try:
        await bot.set_my_commands(commands=commands, scope=BotCommandScopeDefault())
        logger.info("Bot commands registered successfully")
    except Exception as e:
        logger.error(f"Error registering bot commands: {e}", exc_info=True)
    
    # Получаем URL сервера из переменных окружения
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        logger.info(f"Setting webhook to {webhook_url}")
        # Устанавливаем вебхук
        await bot.set_webhook(
            url=webhook_url,
            drop_pending_updates=True
        )
        logger.info("Webhook set successfully")

async def handle_root(request):
    logger.info("Root endpoint accessed")
    return web.Response(
        text="Challenge Bot is running! 🚀\n\nThis is a Telegram bot for group challenges and goal tracking.\n\nBot is available at @Zaruba_resbot",
        content_type="text/plain"
    )

async def handle_webhook(request):
    logger.info("Webhook endpoint accessed")
    try:
        data = await request.json()
        logger.info(f"Received webhook data: {data}")
        return web.Response(text="OK")
    except Exception as e:
        logger.error(f"Error in webhook handler: {e}")
        return web.Response(status=500, text="Internal Server Error")

async def main():
    logger.info("Starting application...")
    # Логируем переменные окружения
    logger.info("Environment variables:")
    logger.info(f"TOKEN: {'*' * len(os.getenv('TOKEN', ''))}")
    logger.info(f"WEBHOOK_URL: {os.getenv('WEBHOOK_URL')}")
    logger.info(f"PORT: {os.getenv('PORT', 8000)}")
    logger.info(f"DB_URL: {os.getenv('DB_URL')}")
    
    # Получаем информацию о боте
    try:
        bot_info = await bot.get_me()
        logger.info(f"Bot information:")
        logger.info(f"Bot ID: {bot_info.id}")
        logger.info(f"Bot username: @{bot_info.username}")
        logger.info(f"Bot name: {bot_info.first_name}")
    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
    
    # Создаем приложение aiohttp
    app = web.Application()
    app.router.add_get("/", handle_root)
    
    # Настраиваем обработчик вебхуков
    webhook_requests_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
    )
    webhook_requests_handler.register(app, path="/webhook")
    
    # Запускаем приложение
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Application started on port {port}")
    await on_startup(bot)
    await web._run_app(app, port=port)

if __name__ == "__main__":
    asyncio.run(main()) 